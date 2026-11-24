"""Closed diagnostic vocabulary at the acquisition process boundaries.

Never serialize exception messages, arbitrary codes, paths or event material.
"""
from .files import SourceError

CODES = frozenset('''
worker_internal_error request_invalid protocol_invalid_json protocol_incomplete
request_too_large request_kind_invalid owner_name_invalid owner_proof_invalid
cancel_event_name_invalid request_root_mismatch account_label_invalid
worker_exit_nonzero worker_result_missing worker_not_verified worker_timeout
owned_tree_not_released owned_reader_not_released
sqlite_integrity_failed workspace_owner_mismatch workspace_unknown_file
ambiguous_group ambiguous_private_participants invalid_group media_scope_limit partition_mismatch unclassified_provider_exclusions
metadata_identity_scope_required metadata_scoped_row_limit metadata_member_scope_mismatch
metadata_group_scope_mismatch metadata_group_identity_ambiguous metadata_group_name_conflict
node_exit_nonzero node_result_missing authentication_unconfirmed image_incomplete
observation_unconfirmed reads_unconfirmed hook_unconfirmed inflight_unconfirmed
snapshot_not_sent resource_changed process_generation_changed process_exit_unconfirmed
permission_denied file_missing io_error cancelled capture_reader_not_released
capture_stop_unconfirmed exact_active_version_required independent_runtime_changed
input_or_generation_changed invalid_capture_status metadata_snapshot_limit module_identity_refused
normal_qq_exit_required selected_process_changed selection_refused snapshot_deadline wrapper_not_ready
unexpected_snapshot_request process_exit_handle_unavailable cancel_event_unavailable
login_window_elapsed capture_deadline
frozen_main_required input_changed invalid_encrypted_size invalid_file invalid_sqlite_size
linked_path local_path_required page_count_mismatch prototype_size_limit unsupported_header untrusted_page_count
invalid_process_selection module_metadata_changed module_metadata_unavailable module_snapshot_unbounded
process_handle_close_failed process_identity_mismatch process_identity_unavailable process_read_access_unavailable
process_detection_failed process_candidate_access_denied
windows_x64_required authorized_partition_mismatch authorized_session_missing_or_ambiguous
database_account_mismatch database_binding_not_unique database_path_shape_unknown encrypted_source_required
full_snapshot_size_limit independent_owner_reference_required owned_snapshot_required preparation_os_check_failed
prepared_snapshot_changed snapshot_copy_limit snapshot_copy_mismatch source_changed source_read_lock_unavailable workspace_overlap
build_refused session_refused frame_limit unexpected_frame closed exit_deadline short_page
deadline_reached source_expired source_cleanup_failed key_source_failed key_not_authenticated passphrase_required
incomplete_event event_size_refused invalid_event_wire event_field_limit ambiguous_event_field
unexpected_response passphrase_event_missing invalid_passphrase_event invalid_request invalid_key_material
source_binding_mismatch trusted_source_unavailable invalid_source source_already_used async_source_unsupported
loader_spawn_failed loader_exit_nonzero loader_timeout transport_write_failed transport_limit
native_install_failed native_ready_failed native_target_failed native_finished_failed native_stop_failed
native_thread_wait_failed native_thread_exit_failed native_pipe_failed native_frame_refused
native_forward_failed native_deadline native_cancel_failed native_diagnostic_failed
transport_header_refused transport_sequence_refused transport_trailing_data transport_parse_refused
transport_refused parse_refused authentication_refused no_target_event
page_hmac_mismatch invalid_sink invalid_size salt_mismatch snapshot_selection_refused snapshot_path_refused
snapshot_identity_refused status_pipe_closed nonzero_capacity_tail invalid_sqlite_header full_decode_deadline
snapshot_read_limit snapshot_short_read snapshot_short_write snapshot_changed plaintext_header_invalid
plaintext_snapshot_invalid short_read short_write full_snapshot_refused database_key_refused
enospc eacces eperm eio emfile enomem enoent eexist enotdir eloop ebusy erofs efbig einval enfile ebadf
err_out_of_range err_crypto_invalid_keylen err_ossl_bad_decrypt
'''.split())
STAGES = frozenset(('admission','transport','event','exit','snapshot','message','group_info',
                    'profile_info','final_check','cleanup','protocol'))


def safe_code(code):
    return code.lower() if isinstance(code,str) and code.lower() in CODES else 'worker_internal_error'


def failure_record(error=None, *, code=None, stage='protocol', exit_code=None, cause_code=None, native_results=None):
    if code is None:
        if isinstance(error,SourceError):code=error.code
        elif isinstance(error,PermissionError):code='permission_denied'
        elif isinstance(error,FileNotFoundError):code='file_missing'
        elif isinstance(error,OSError):code='io_error'
    result={'phase':'failed','verified':False,'failure_code':safe_code(code),
            'failure_stage':stage if isinstance(stage,str) and stage in STAGES else 'protocol'}
    if exit_code is None:exit_code=getattr(error,'diagnostic_exit_code',None)
    if type(exit_code) is int and -(2**31)<=exit_code<2**32:result['loader_exit_code']=exit_code
    if cause_code is None:
        cause_code=getattr(error,'diagnostic_cause_code',None)
        context=getattr(error,'__context__',None)
        if cause_code is None and isinstance(context,SourceError):cause_code=context.code
    if cause_code is not None:result['cause_code']=safe_code(cause_code)
    if native_results is None:native_results=getattr(error,'diagnostic_native_results',None)
    if isinstance(native_results,dict):
        fields=('install','ready','target','finished','stop','thread')
        result['native_results']={name:value if isinstance(value:=native_results.get(name),str)
            and value in {'unknown','passed','failed'} else 'unknown' for name in fields}
    return result


def public_message(code, *, loader_exit_code=None):
    code=safe_code(code)
    if code in {'cancelled','deadline_reached','exit_deadline','normal_qq_exit_required','capture_deadline','worker_timeout'}:
        message='本次获取已取消或等待超时，未继续读取。'
    elif code in {'key_not_authenticated','page_hmac_mismatch','database_key_refused','authentication_refused'}:
        message='所选资料未通过凭据认证，未开放聊天列表。'
    elif code in {'observation_unconfirmed','reads_unconfirmed','hook_unconfirmed','inflight_unconfirmed','source_cleanup_failed'}:
        message='未能确认连接组件已安全停止，本次获取已终止。'
    elif code == 'process_candidate_access_denied':
        message='Windows 拒绝访问当前桌面上的 QQ 进程，无法确认它是否为所选 QQ。请从托盘完全退出 QQ，重新连接后按提示以普通权限打开所选 QQ。'
    elif code == 'process_detection_failed':
        message='无法确认 QQ 的运行状态。请从托盘完全退出 QQ，再重新连接。'
    elif code in {'process_read_access_unavailable','process_identity_unavailable','process_exit_handle_unavailable'}:
        message='无法验证所选 QQ 的进程信息。请从托盘完全退出 QQ，重新连接后按提示以普通权限打开所选 QQ。'
    elif code == 'loader_exit_nonzero' and loader_exit_code == 28:
        # The pinned loader uses 28 for the process open, creation time, and image checks.
        message='连接组件无法访问所选 QQ 或验证其进程身份。请从托盘完全退出 QQ，重新连接后按提示以普通权限打开所选 QQ。'
    elif code in {'selected_process_changed','process_generation_changed','process_identity_mismatch'}:
        message='所选 QQ 进程已变化。请重新连接，并按提示打开 QQ、停留在登录界面。'
    elif code == 'wrapper_not_ready':
        message='所选 QQ 的登录组件未能及时就绪。请从托盘完全退出 QQ，重新连接后停留在登录界面。'
    else:
        message='QQ 数据获取未完成，本次操作已停止。'
    return f'{message}（错误码：qq_capture_{code}）'
