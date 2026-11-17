"""Independent acquisition behavior for the existing QQ workspace controls.

The workspace owns layout and analysis; the Facade owns data and resources.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QFileDialog, QInputDialog, QMessageBox

from ..application.connection_models import ConnectionState
from ..application.facade import ChatSource


class QQIndependentConnection:
    def __init__(self, workspace):
        self.view = workspace
        self.facade = workspace._facade
        self.cancelled = Event()
        self.running = False
        self._operation = None
        self._journey = False
        self._image = None
        self._data_root = None
        self._recovery = 'data'
        self._recover_media = False
        self._login_deadline = None
        self._timer = QTimer(workspace)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._login_tick)
        workspace._progress_track.STAGES = ('准备', '登录', '读取', '连接')
        workspace._qq_settings_button.clicked.connect(self._settings)
        self._idle()

    def _action(self, action, note, stage=0):
        v = self.view
        v._set_stage(stage)
        v._show_qq_guide(action, note)
        v.status_changed.emit(action)

    def _idle(self, message=None, *, recovery=False, blocked=False):
        v = self.view
        self._journey = False
        v._sessions_loaded = False
        v._qq_status_timer.stop()
        v.session_panel.clear()
        v.session_panel.show_unconnected_placeholder()
        v.session_panel.setEnabled(False)
        v._set_stage(None)
        v._status_label.setText('QQ 连接已停止' if blocked else 'QQ 未连接')
        v._status_label.show()
        v._show_qq_guide('连接 QQ', message or
            '连接期间需要你按提示登录并完全退出 QQ，读取完成后可重新打开。\n聊天记录仅在本机处理。')
        v._qq_connect_button.setText('连接已停止' if blocked else '重新连接' if message else '连接 QQ')
        v._qq_connect_button.setEnabled(not blocked)
        v._qq_connect_button.show()
        v._qq_disconnect_button.hide()
        v._qq_settings_button.setVisible(recovery)
        v._update_setup_spacing()
        v.status_changed.emit(message or 'QQ 未连接')

    def _submit(self, operation, success, *, progress=False, cleanup=True):
        if self.running or self.view._closing:
            return
        self.running = True
        identity = object()
        self._operation = identity
        result = []
        failure = []

        def current():
            return not self.view._closing and self._operation is identity

        def finished():
            if not current():
                return
            self.running = False
            self._operation = None
            self._timer.stop()
            if cleanup and self.cancelled.is_set():
                self.release('已取消连接，可以重新开始。')
            elif failure:
                _code, message = failure[0]
                if cleanup:
                    self._image = None
                    self.release(message)
                else:
                    self._idle('本次资料未能安全释放，已停止连接。请关闭 Echo，暂勿重复连接。', blocked=True)
            elif result:
                success(result[0])

        self.view._executor(operation,
            on_success=lambda value: result.append(value) if current() else None,
            on_error=lambda code, message: failure.append((code, message)) if current() else None,
            on_finished=finished,
            **({'on_progress': lambda value: self._progress(value)
                if current() and not self.cancelled.is_set() else None} if progress else {}))

    def connect(self):
        if self.running:
            self.cancel()
            return
        if self.view._closing:
            return
        self.cancelled = Event()
        cancel = self.cancelled
        self._journey = True
        v = self.view
        v.session_panel.clear()
        v.session_panel.setEnabled(False)
        v._qq_settings_button.hide()
        v._qq_disconnect_button.hide()
        v._qq_connect_button.setText('取消连接')
        v._qq_connect_button.setEnabled(True)
        self._action('正在寻找 QQ 聊天记录', '请稍候，无需操作。')
        self._submit(lambda: self.facade.discover_independent_qq_profiles(
            self._data_root, cancelled=cancel.is_set), self._discovered)

    def _discovered(self, discovery):
        if not discovery.accounts:
            self._recovery = 'data'
            self._idle('没有找到 QQ 聊天记录，请通过连接设置选择资料位置。', recovery=True)
            return
        accounts = discovery.accounts
        labels = [path.name for path in accounts]
        if len(set(labels)) != len(labels):
            self._recovery = 'data'
            self._idle('发现多个同号资料，请通过连接设置明确选择一个账号资料位置。', recovery=True)
            return
        if len(accounts) > 1:
            label, accepted = QInputDialog.getItem(self.view, '选择 QQ 账号',
                '选择本次要分析的账号资料', labels, 0, False)
            if not accepted:
                self.release('已取消选择账号。')
                return
            account = accounts[labels.index(label)]
        else:
            account = accounts[0]
        if self._image is None:
            if not discovery.executables:
                self._recovery = 'program'
                if discovery.incompatible_executables:
                    message = '已找到 QQ，但当前版本不受支持。请使用 QQ 9.9.37（54395）后重新连接。'
                elif discovery.unverified_executables:
                    message = '已找到 QQ，但无法验证程序完整性或活动版本。请修复 QQ 安装后重新连接。'
                else:
                    message = '没有找到已安装的 QQ。请安装 QQ 9.9.37（54395）后重新连接。'
                self._idle(message, recovery=True)
                return
            if len(discovery.executables) == 1:
                self._image = discovery.executables[0]
            else:
                choices = [f'QQ 9.9.37（54395） · {path.parent}' for path in discovery.executables]
                choice, accepted = QInputDialog.getItem(self.view, '选择 QQ',
                    '发现多个兼容的 QQ，请选择本次使用的程序', choices, 0, False)
                if not accepted:
                    self.release('已取消选择 QQ。')
                    return
                self._image = discovery.executables[choices.index(choice)]
        if not self._authorize(account):
            self.release('尚未授权读取，可以重新选择账号。')
            return
        if self.view._closing:
            return
        self._account = account
        cancel = self.cancelled
        image = self._image
        recover_media = self._recover_media
        self._action('正在准备连接 QQ', '请先不要登录，等待 Echo 的下一步提示。')

        def acquire(report):
            self.facade.prepare_independent_qq(image, account,
                recover_media=recover_media, cancelled=cancel.is_set)
            return self.facade.start_qq_auth_flow(progress=report, cancel_event=cancel,
                wait_for_process=True)

        self._submit(acquire, self._confirm_identity, progress=True)

    def _authorize(self, account):
        dialog = QMessageBox(QMessageBox.Icon.Question, '授权本机读取',
            f'允许 Echo 在本机读取账号 {account.name} 的群聊和私聊，用于生成报告？\n'
            '请只授权你本人有权分析的资料。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self.view)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText('允许读取')
        dialog.button(QMessageBox.StandardButton.No).setText('暂不连接')
        media = QCheckBox('恢复报告图片（可能联网获取缺失表情）', dialog)
        dialog.setCheckBox(media)
        accepted = dialog.exec() == QMessageBox.StandardButton.Yes
        self._recover_media = accepted and media.isChecked()
        return accepted

    def _progress(self, value):
        if not isinstance(value, dict):
            return
        self._timer.stop()
        self._login_deadline = None
        phase = value.get('phase')
        if phase == 'preparation_exit':
            self._action('请先完全退出 QQ',
                '检测到 QQ 正在运行，本次连接需要重新登录。若开启了自动登录，请先关闭；然后从系统托盘退出 QQ，Echo 会自动继续。')
        elif phase == 'waiting_for_qq':
            self._action('请打开 QQ，先不要登录',
                '请停留在登录界面，等待 Echo 提示。如果 QQ 自动进入聊天界面，请取消本次连接并先关闭自动登录。')
        elif phase == 'armed':
            remaining = min(value['remaining_login_ms'] / 1000,
                (datetime.fromisoformat(value['login_before_utc']) - datetime.now(timezone.utc)).total_seconds())
            self._login_deadline = time.monotonic() + max(0, remaining)
            self._timer.start()
            self._login_tick()
        elif phase == 'awaiting_exit':
            self._action('请完全退出 QQ',
                '请从系统托盘退出 QQ，以便读取完整记录。Echo 会自动继续；聊天列表出现前请勿重新打开。', 2)
        elif phase == 'authenticating':
            self._action('正在读取聊天记录', '请稍候，无需操作。', 2)
        elif phase == 'stopped':
            self._action('正在连接 QQ', '请稍候，等待下一步提示。', 1)

    def _login_tick(self):
        if self.view._closing or self.cancelled.is_set() or self._login_deadline is None:
            self._timer.stop()
            return
        remaining = int(self._login_deadline - time.monotonic())
        if remaining <= 0:
            self.cancel()
            self._action('本次登录等待已结束', '请勿继续登录，清理完成后可重新连接。', 1)
        else:
            self._action('现在可以登录 QQ', f'请在 {remaining} 秒内正常登录所选账号。', 1)

    def _confirm_identity(self, _snapshot):
        self._action('确认本人 QQ 号', '该号码用于区分报告中的本人消息。', 3)
        account, accepted = QInputDialog.getText(self.view, '确认本人 QQ 号',
            '下方号码来自所选资料标签，请核对是否为本人 QQ 号。\n此身份由你声明，并非 QQ 系统认证。', text=self._account.name)
        if not accepted:
            self.release('已取消本人身份确认。')
            return
        cancel = self.cancelled
        self._action('正在加载聊天列表', '请稍候，无需操作。', 3)

        def load():
            self.facade.confirm_independent_qq_account(account.strip(), cancelled=cancel.is_set)
            return self.facade.list_sessions(ChatSource.QQ, cancelled=cancel.is_set)

        self._submit(load, self._ready)

    def _ready(self, sessions):
        v = self.view
        self._journey = False
        v.session_panel.setEnabled(True)
        v._handle_sessions_loaded(sessions)
        v._status_label.setText('QQ 聊天记录已就绪 · 本人身份由你确认\n现在可以重新打开 QQ。')
        v._qq_connect_button.hide()
        v._qq_settings_button.hide()
        v._qq_disconnect_button.setEnabled(True)
        v._qq_disconnect_button.show()
        v._qq_status_timer.start()

    def cancel(self):
        self._timer.stop()
        self.cancelled.set()
        self.facade.cancel_qq_auth_flow(self.cancelled)
        self.view.session_panel.cancel_analysis()
        if not self.view._closing:
            if self.running:
                self.view._qq_connect_button.setEnabled(False)
                self._action('正在取消连接', '正在释放本次读取的资料，请稍候。')
            else:
                self.release('已取消连接。')

    def release(self, message=None, *, recovery=False):
        if self.running:
            self.cancel()
            return
        self._timer.stop()
        v = self.view
        v._qq_status_timer.stop()
        v.session_panel.cancel_analysis()
        v.session_panel.clear()
        v.session_panel.setEnabled(False)
        v._sessions_loaded = False
        v._qq_disconnect_button.hide()
        v._qq_connect_button.setEnabled(False)
        self._action('正在结束连接', '正在释放本次读取的资料，请稍候。')
        self._submit(self.facade.disconnect_qq,
            lambda _: self._idle(message, recovery=recovery), cleanup=False)

    def refresh(self):
        if self.view._closing or self.running or self._journey or not self.view._sessions_loaded:
            return
        self._submit(self.facade.get_qq_connection_snapshot, self._refreshed)

    def _refreshed(self, snapshot):
        if snapshot.state is not ConnectionState.CONNECTED:
            self.release('临时聊天记录已释放。如需继续分析，请重新连接 QQ。')

    def _settings(self):
        if self.running or self.view._closing:
            return
        if self._recovery == 'program':
            value, _ = QFileDialog.getOpenFileName(self.view, '选择 QQ 程序',
                str(self._image.parent if self._image else Path.home()), 'QQ 程序 (QQ.exe)')
            if value:
                self._image = Path(value)
        else:
            value = QFileDialog.getExistingDirectory(self.view, '选择 QQ 资料位置', str(Path.home() / 'Documents'))
            if value:
                self._data_root = Path(value)
        if value:
            self.connect()
