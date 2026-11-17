"""Guided local QQ acquisition, sharing the standard conversation analysis UI."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ..application.connection_models import ConnectionState
from ..application.facade import ChatSource
from .session_analysis_panel import SessionAnalysisPanel
from .workers import submit


class QQIndependentWorkspace(QWidget):
    analysis_started = Signal()
    analysis_succeeded = Signal(object)
    analysis_failed = Signal(str, str)
    analysis_phase_changed = Signal(object)
    status_changed = Signal(str)

    def __init__(self, facade: Any, parent=None, *, executor=None):
        super().__init__(parent)
        self._facade=facade;self._executor=executor or submit
        self._closing=False;self._cancel=Event();self._running=False
        self._phase='select';self._operation=None;self._login_deadline=None
        layout=QVBoxLayout(self)
        heading=QLabel('QQ · 本地聊天分析');heading.setObjectName('workspaceTitle');layout.addWidget(heading)
        self._guide=QWidget();guide=QVBoxLayout(self._guide);layout.addWidget(self._guide)
        intro=QLabel('选择并授权一个本地 QQ 账号资料。请使用 QQ 9.9.37（54395）。\n'
            '授权 → 等待 Echo 就绪 → 正常登录 → 完全退出 QQ → 确认本人 → 选择聊天与时间。')
        intro.setWordWrap(True);guide.addWidget(intro)
        form=QFormLayout();guide.addLayout(form)
        self._executable,self._choose_executable=self._path_row(form,'QQ 程序','选择 QQ.exe',False)
        self._account_directory,self._choose_account=self._path_row(form,'账号资料','选择数字账号目录',True)
        self._authorization=QCheckBox('我有权分析所选账号资料，并授权 Echo 在本机读取其中的群聊与私聊。')
        guide.addWidget(self._authorization)
        self._media=QCheckBox('恢复报告图片（使用此账号的本地缓存；缺失表情可能访问固定素材 CDN）')
        guide.addWidget(self._media)
        row=QHBoxLayout();guide.addLayout(row)
        self._prepare_button=QPushButton('授权资料并继续');self._prepare_button.clicked.connect(self._prepare)
        self._capture_button=QPushButton('等待登录');self._capture_button.clicked.connect(self._capture)
        row.addWidget(self._prepare_button);row.addWidget(self._capture_button);row.addStretch()
        self._confirmation=QWidget();confirmation=QHBoxLayout(self._confirmation)
        confirmation.addWidget(QLabel('本人 QQ 号（用户声明）'))
        self._declared_account=QLineEdit();self._declared_account.setMaxLength(20);confirmation.addWidget(self._declared_account)
        self._confirm_button=QPushButton('确认并列出聊天');self._confirm_button.clicked.connect(self._confirm)
        confirmation.addWidget(self._confirm_button);guide.addWidget(self._confirmation)
        self._status=QLabel('请选择 QQ.exe 和一个数字账号目录（其中应有 nt_qq/nt_db）。')
        self._status.setWordWrap(True);self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_row=QHBoxLayout();status_row.addWidget(self._status,1)
        self._cancel_button=QPushButton('取消／释放资料');self._cancel_button.clicked.connect(self._release)
        status_row.addWidget(self._cancel_button);layout.addLayout(status_row)
        self._session_panel=SessionAnalysisPanel(self)
        self._session_panel.configure(facade,ChatSource.QQ,self._executor)
        for name in ('analysis_started','analysis_succeeded','analysis_failed','analysis_phase_changed','status_changed'):
            getattr(self._session_panel,name).connect(getattr(self,name).emit)
        layout.addWidget(self._session_panel,1)
        self._timer=QTimer(self);self._timer.setInterval(250);self._timer.timeout.connect(self._login_tick)
        self._update_controls()

    def _path_row(self, form, title, button_text, directory):
        row=QWidget();box=QHBoxLayout(row);box.setContentsMargins(0,0,0,0)
        field=QLineEdit();field.setReadOnly(True);box.addWidget(field,1)
        button=QPushButton(button_text);box.addWidget(button)
        def choose():
            value=(QFileDialog.getExistingDirectory(self,'选择一个数字账号目录') if directory else
                QFileDialog.getOpenFileName(self,'选择 QQ.exe','','QQ 程序 (QQ.exe)')[0])
            if value:field.setText(value)
        button.clicked.connect(choose);form.addRow(title,row)
        return field,button

    def _set_status(self, text):
        self._status.setText(text);self.status_changed.emit(text)

    def _update_controls(self):
        selecting=self._phase=='select' and not self._running
        for widget in (self._choose_executable,self._choose_account,self._authorization,self._media):widget.setEnabled(selecting)
        self._prepare_button.setEnabled(selecting)
        self._capture_button.setEnabled(self._phase=='prepared' and not self._running)
        self._confirmation.setVisible(self._phase=='confirm')
        self._confirm_button.setEnabled(not self._running)
        self._session_panel.setEnabled(self._phase=='ready' and not self._running)
        self._guide.setVisible(self._phase!='ready')

    def _submit(self, operation, success, *, progress=False, cleanup_on_cancel=True):
        if self._running or self._closing:return
        self._running=True;identity=object();cancel=self._cancel;self._operation=identity;self._update_controls()
        def current():return not self._closing and self._operation is identity
        def done(value):
            if current() and (not cleanup_on_cancel or not cancel.is_set()):success(value)
        def error(_code,message):
            if current():
                self._phase='select';self._session_panel.clear();self._set_status(message)
        def finish():
            if current():
                self._running=False;self._operation=None;self._timer.stop();self._update_controls()
                if cleanup_on_cancel and cancel.is_set():self._release()
        self._executor(operation,on_success=done,on_error=error,on_finished=finish,
            **({'on_progress':lambda value:self._progress(value) if current() else None} if progress else {}))

    def _prepare(self):
        if not self._authorization.isChecked() or not self._executable.text() or not self._account_directory.text():
            self._set_status('请先选择 QQ.exe、账号资料目录，并勾选本地读取授权。');return
        self._cancel=Event();cancel=self._cancel
        image=Path(self._executable.text());account=Path(self._account_directory.text());media=self._media.isChecked()
        self._set_status('正在验证程序与授权资料位置…')
        def ready(snapshot):
            self._phase='prepared';self._set_status(snapshot.message)
        self._submit(lambda:self._facade.prepare_independent_qq(image,account,recover_media=media,cancelled=cancel.is_set),ready)

    def _capture(self):
        cancel=self._cancel
        self._set_status('正在准备登录捕获，请暂不登录 QQ…')
        def captured(snapshot):
            self._phase='confirm';self._declared_account.setText(Path(self._account_directory.text()).name)
            self._set_status(snapshot.message+' 该声明用于报告中的本人／对方区分。')
        self._submit(lambda report:self._facade.start_qq_auth_flow(progress=report,cancel_event=cancel),captured,progress=True)

    def _progress(self,value):
        self._timer.stop();self._login_deadline=None
        if isinstance(value,dict) and value.get('phase')=='armed':
            remaining=min(value['remaining_login_ms']/1000,
                (datetime.fromisoformat(value['login_before_utc'])-datetime.now(timezone.utc)).total_seconds())
            self._login_deadline=time.monotonic()+max(0,remaining);self._timer.start();self._login_tick()
        elif isinstance(value,str):self._set_status(value)

    def _login_tick(self):
        if self._closing or self._login_deadline is None:return
        remaining=int(self._login_deadline-time.monotonic())
        if remaining<=0:
            self._timer.stop();self._set_status('本次登录窗口已结束，请勿继续登录；等待任务结束后重新准备。')
        else:self._set_status(f'Echo 已就绪，请在 {remaining} 秒内正常登录所选账号。收到提示后，请从托盘完全退出 QQ。')

    def _confirm(self):
        account=self._declared_account.text().strip();cancel=self._cancel
        self._set_status('正在读取完整群聊与私聊列表…')
        def load():
            self._facade.confirm_independent_qq_account(account,cancelled=cancel.is_set)
            return self._facade.list_sessions(ChatSource.QQ,cancelled=cancel.is_set)
        def ready(sessions):
            self._phase='ready';self._session_panel.populate_sessions(sessions)
            self._set_status('本人身份由用户声明，非 QQ 系统认证。请选择聊天和时间范围；闲置 10 分钟后释放快照。')
        self._submit(load,ready)

    def _release(self):
        self._timer.stop()
        if self._running:
            self.cancel_connection();self._set_status('正在取消并清理本次资料…');return
        self._session_panel.clear()
        def released(snapshot):self._phase='select';self._set_status(snapshot.message)
        self._submit(self._facade.disconnect_qq,released,cleanup_on_cancel=False)

    def cancel_connection(self):
        self._timer.stop();self._cancel.set()
        self._facade.cancel_qq_auth_flow(self._cancel)
        self.cancel_analysis()

    def cancel_analysis(self):self._session_panel.cancel_analysis()

    def select_source(self, _source):pass

    def refresh_connection_status(self, *, load_sessions_on_ready=False):
        if self._closing or self._running:return
        snapshot=self._facade.get_qq_connection_snapshot()
        if self._phase=='ready' and snapshot.state is ConnectionState.DISCONNECTED:
            self._phase='select';self._session_panel.clear();self._set_status('快照已释放，请重新获取 QQ 资料。');self._update_controls()
        self.status_changed.emit(self._status.text())
