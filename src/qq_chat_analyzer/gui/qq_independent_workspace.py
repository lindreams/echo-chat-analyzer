"""Normal QQ-client login guidance, with the existing shared analysis panel."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from threading import Event
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout,
                              QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)
from ..application.facade import ChatSource
from .session_analysis_panel import SessionAnalysisPanel
from .workers import submit


class QQIndependentWorkspace(QWidget):
    analysis_started=Signal()
    analysis_succeeded=Signal(object)
    analysis_failed=Signal(str,str)
    analysis_phase_changed=Signal(object)
    status_changed=Signal(str)

    def __init__(self, facade: Any, parent=None, *, executor=None):
        super().__init__(parent)
        self._facade=facade; self._executor=executor or submit
        self._cancel=Event(); self._running=False; self._closing=False
        self._login_prompt=QTimer(self)
        self._login_prompt.setSingleShot(True)
        self._login_prompt.timeout.connect(self._login_expired)
        layout=QVBoxLayout(self)
        heading=QLabel('QQ · 本地独立读取'); heading.setObjectName('workspaceTitle'); layout.addWidget(heading)
        self._guide=QLabel('支持 Windows QQ 9.9.37-54395 群聊。先正常退出 QQ，再准备快照。'
                          '本轮仅读取你指定的账号和群；不会关闭或重启 QQ。')
        self._guide.setWordWrap(True); self._guide.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self._guide)
        self._form=QWidget(); form=QFormLayout(self._form); layout.addWidget(self._form)
        self._executable=QLineEdit(); self._account_directory=QLineEdit()
        self._account=QLineEdit(); self._group=QLineEdit()
        for label,field,folder in (('QQ 程序',self._executable,False),('账号数据目录',self._account_directory,True)):
            row=QHBoxLayout(); row.addWidget(field); pick=QPushButton('选择…'); row.addWidget(pick)
            pick.clicked.connect(lambda _=False,f=field,d=folder:self._choose(f,d)); form.addRow(label,row)
        self._account_directory.setPlaceholderText('选择以 QQ 账号命名、含 nt_qq 文件夹的目录')
        form.addRow('QQ 账号',self._account); form.addRow('授权群号',self._group)
        self._media=QCheckBox('恢复此账号本地表情图片；缺失 MFACE 使用已有 raw200 预览'); self._media.setChecked(True)
        form.addRow(self._media)
        actions=QHBoxLayout(); layout.addLayout(actions)
        self._prepare=QPushButton('1. QQ 已退出，准备快照')
        self._observe=QPushButton('2. QQ 已打开，等待登录'); self._observe.setEnabled(False)
        self._stop=QPushButton('取消 / 释放本次数据'); self._stop.setEnabled(False)
        for button in (self._prepare,self._observe,self._stop): actions.addWidget(button)
        self._prepare.clicked.connect(self.prepare); self._observe.clicked.connect(self.observe); self._stop.clicked.connect(self.cancel_connection)
        self._status=QLabel('已登录的 QQ 暂不支持直接接入。请先正常退出，再按上述步骤重新登录。')
        self._status.setWordWrap(True); self._status.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self._status)
        self._session_panel=SessionAnalysisPanel(self); self._session_panel.configure(facade,ChatSource.QQ,self._executor)
        layout.addWidget(self._session_panel,1)
        for name in ('analysis_started','analysis_succeeded','analysis_failed','analysis_phase_changed','status_changed'):
            getattr(self._session_panel,name).connect(getattr(self,name).emit)
        self._session_panel.analysis_succeeded.connect(self._consumed)

    def _choose(self,field,folder):
        value=(QFileDialog.getExistingDirectory(self,'选择当前账号的数据目录') if folder else
               QFileDialog.getOpenFileName(self,'选择 QQ.exe','','QQ 程序 (QQ.exe)')[0])
        if value:
            field.setText(value)
            if folder: self._account.setText(Path(value).name)

    def _message(self,text):
        if self._closing:return
        self._login_prompt.stop()
        if isinstance(text,dict):
            # Queued progress must not invite login after the native deadline.
            try:
                deadline=datetime.fromisoformat(text['login_before_utc'])
                remaining=min(text['remaining_login_ms'],int((deadline-datetime.now(timezone.utc)).total_seconds()*1000))
                if text.get('phase')!='armed' or remaining<=0:raise ValueError('expired')
            except (KeyError,TypeError,ValueError):
                self._login_expired();return
            self._login_prompt.start(remaining)
            text=f'armed：现在请在 QQ 客户端正常登录，剩余约 {remaining//1000} 秒。'
        self._status.setText(str(text)); self.status_changed.emit(str(text))

    def _login_expired(self):
        self._cancel.set(); self._facade.cancel_qq_auth_flow(self._cancel)
        self._message('登录观察窗口已结束，正在清理。请正常退出 QQ 后重新准备。')

    def _run(self,operation,success):
        if self._running or self._closing:return
        self._running=True; self._prepare.setEnabled(False); self._observe.setEnabled(False)
        self._form.setEnabled(False); self._stop.setEnabled(True); self._cancel=Event()
        def failed(_code,message): self._message(message)
        def finished():
            self._login_prompt.stop()
            self._running=False
            if self._closing:return
            self._form.setEnabled(True); self._prepare.setEnabled(True)
        self._executor(operation,on_success=lambda value:success(value) if not self._closing else None,
                       on_error=failed,on_finished=finished,on_progress=self._message)

    def prepare(self):
        values=(self._executable.text().strip(),self._account_directory.text().strip(),
                self._account.text().strip(),self._group.text().strip())
        recover_media=self._media.isChecked()
        self._session_panel.clear()
        def operation(report):
            report('正在冻结本地数据库，请保持 QQ 完全退出…')
            return self._facade.prepare_independent_qq(*values,recover_media=recover_media,cancelled=self._cancel.is_set)
        def done(snapshot):
            self._message(snapshot.message); self._observe.setEnabled(True)
        self._run(operation,done)

    def observe(self):
        def operation(report):
            report('正在连接所选 QQ，请暂不登录，等待 armed 提示…')
            self._facade.start_qq_auth_flow(progress=report,cancel_event=self._cancel)
            return self._facade.list_sessions(ChatSource.QQ,cancelled=self._cancel.is_set)
        def done(sessions):
            self._session_panel.populate_sessions(sessions)
            self._message('授权群快照已就绪，十分钟内可生成一次报告。读取组件已停止；请正常退出 QQ 以完全释放组件。')
        self._run(operation,done)

    def cancel_connection(self):
        self._login_prompt.stop()
        self._cancel.set(); self._facade.cancel_qq_auth_flow(self._cancel)
        self._session_panel.cancel_analysis()
        if self._closing:return  # Facade shutdown owns cleanup; never enqueue new work.
        if not self._running:
            self._session_panel.clear(); self._observe.setEnabled(False)
            self._run(lambda _report:self._facade.disconnect_qq(),
                      lambda _:self._message('本次数据已清理。若已等待登录，请正常退出 QQ 以完全释放组件。'))
        else:self._message('正在取消并清理，请稍候。若已等待登录，请正常退出 QQ 以完全释放组件。')

    def cancel_analysis(self): self._session_panel.cancel_analysis()

    def _consumed(self,_outcome):
        self._session_panel.clear(); self._observe.setEnabled(False)
        self._message('报告已生成，本次临时数据已释放。再次读取需要正常退出 QQ 后重新准备。')

    def select_source(self,_source): pass

    def refresh_connection_status(self,*,load_sessions_on_ready=False):
        # Navigation is passive: no process inspection, new acquisition or login.
        if self._running:return
        self._message(self._facade.get_qq_connection_snapshot().message)
