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
node_exit_nonzero node_result_missing authentication_unconfirmed image_incomplete
observation_unconfirmed reads_unconfirmed hook_unconfirmed inflight_unconfirmed
snapshot_not_sent resource_changed process_generation_changed process_exit_unconfirmed
permission_denied file_missing io_error cancelled capture_reader_not_released
capture_stop_unconfirmed exact_active_version_required independent_runtime_changed
input_or_generation_changed invalid_capture_status metadata_snapshot_limit module_identity_refused
normal_qq_exit_required selected_process_changed selection_refused snapshot_deadline
unexpected_snapshot_request process_exit_handle_unavailable cancel_event_unavailable
login_window_elapsed capture_deadline
frozen_main_required input_changed invalid_encrypted_size invalid_file invalid_sqlite_size
linked_path local_path_required page_count_mismatch prototype_size_limit unsupported_header untrusted_page_count
invalid_process_selection module_metadata_changed module_metadata_unavailable module_snapshot_unbounded
process_handle_close_failed process_identity_mismatch process_identity_unavailable process_read_access_unavailable
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


def failure_record(error=None, *, code=None, stage='protocol', exit_code=None, cause_code=None):
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
    return result


def public_message(code):
    code=safe_code(code)
    if code in {'cancelled','deadline_reached','exit_deadline','normal_qq_exit_required','capture_deadline','worker_timeout'}:
        message='本次获取已取消或等待超时，未继续读取。'
    elif code in {'key_not_authenticated','page_hmac_mismatch','database_key_refused','authentication_refused'}:
        message='所选资料未通过凭据认证，未开放聊天列表。'
    elif code in {'observation_unconfirmed','reads_unconfirmed','hook_unconfirmed','inflight_unconfirmed','source_cleanup_failed'}:
        message='未能确认连接组件已安全停止，本次获取已终止。'
    else:
        message='QQ 数据获取未完成，本次操作已停止。'
    return f'{message}（错误码：qq_capture_{code}）'
