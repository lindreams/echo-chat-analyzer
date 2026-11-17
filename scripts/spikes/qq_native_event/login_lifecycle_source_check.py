"""Disk-only evidence for the 54395 login observation-point correction.

Never opens a process, loads wrapper.node, installs a hook or reads account data.
The pinned reference bundle is inspected, never imported or executed.
"""
import hashlib
import json
from pathlib import Path
import struct

import pefile

from identity_layout_check import inspect
from login_lifecycle_layout import POINTS, VTABLE


def check():
    module, base, _ = inspect()
    pe = pefile.PE(str(module), fast_load=True)
    try:
        image = pe.get_memory_mapped_image()
        entry = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        functions = {(a, b) for a, b, _ in struct.iter_unpack('<III', pe.get_data(entry.VirtualAddress, entry.Size))}

        def edge(at, target, opcode):
            assert image[at] == opcode
            assert at+5+struct.unpack_from('<i', image, at+1)[0] == target

        def has_call(begin, end, target):
            assert any(image[at] == 0xe8 and at+5+struct.unpack_from('<i', image, at+1)[0] == target
                       for at in range(begin, end-4))

        def cstring(at):
            return image[at:image.index(b'\0', at)]

        factories = {'User': 0x22ae262, 'State': 0x22ac730, 'Logout': 0x22adbe2,
                     'Disconnected': 0x22ab43c, 'Connecting': 0x22ab776,
                     'Success': 0x22acb0c, 'Connected': 0x22ab102}
        points = (*POINTS,
            ('Success', 8, 0x22a9cc8, 0x22a9d5c, 0x22acc31, 0x22acd7e,
             b'onQRCodeLoginSucceed', bytes.fromhex('48 89 48 f8')),
            ('Connected', 1, 0x22a9706, 0x22a977d, 0x22ab239, 0x22ab366,
             b'onLoginConnected', bytes.fromhex('48 89 4a 10')))
        records = []
        for label, slot, begin, end, proxy, proxy_end, name, flow in points:
            assert (begin, end) in functions and image[begin:end].count(flow) == 1
            assert struct.unpack_from('<Q', image, VTABLE+slot*8)[0] == base+begin
            factory = factories[label]
            factory_end = next(b for a, b in functions if a == factory)
            has_call(begin, end, factory)
            invokers = []
            for at in range(factory, factory_end-6):
                # Both inline-storage and heap-storage deferred invoke paths.
                if image[at:at+3] == bytes.fromhex('48 8d 15'):
                    invoker = at+7+struct.unpack_from('<i', image, at+3)[0]
                    assert any(image[p] == 0xe9 and p+5+struct.unpack_from('<i', image, p+1)[0] == proxy
                               for p in range(invoker, invoker+32))
                    invokers.append(hex(invoker))
            assert len(invokers) == 2
            assert (proxy, proxy_end) in functions
            # Bind the named JS property to this proxy, not a nearby function.
            assert any(image[p:p+3] == bytes.fromhex('4c 8d 05') and
                       cstring(p+7+struct.unpack_from('<i', image, p+3)[0]) == name
                       for p in range(proxy, proxy_end-6))
            records.append({'event': name.decode(), 'slot': slot, 'native': hex(begin),
                            'factory': hex(factory), 'invokers': invokers, 'proxy': hex(proxy),
                            'native_sha256': hashlib.sha256(image[begin:end]).hexdigest()})

        # addKernelLoginListener -> shared listener construction -> JS reference.
        for caller, target in ((0xdb7000, 0xdb7123), (0xdb7145, 0xdc1e3f),
                               (0xdc1e79, 0xdc1ed6), (0xdc1f08, 0xdc1f5c)):
            edge(caller, target, 0xe8)
        edge(0xdc1f62, 0x22a9644, 0xe9)
        assert image[0xdb7060:0xdb7063] == bytes.fromhex('ff 50 08')
        assert image[0xdb7286:0xdb7289] == bytes.fromhex('ff 50 10')
        pe.parse_data_directories(directories=[1])
        imports = {s.address-base: s.name for d in pe.DIRECTORY_ENTRY_IMPORT for s in d.imports}
        assert imports[0x4b098b0] == b'napi_create_reference'
        assert image[0x22a9676:0x22a967c] == bytes.fromhex('ff 15 34 02 86 02')

        # The success argument is an object, NOT the uint64 argument of User.
        has_call(0x22a9cc8, 0x22a9d5c, 0x22a9dc2)
        assert image[0x22a9df6:0x22a9dfa] == bytes.fromhex('48 8b 46 30')
        assert image[0x22a9dfe:0x22a9e02] == bytes.fromhex('48 89 41 30')
        has_call(0x22acc31, 0x22acd7e, 0x22acdaa)
        assert image[0x22ace7e:0x22ace82] == bytes.fromhex('48 8b 57 30')
        assert cstring(0x22acec5+7+struct.unpack_from('<i', image, 0x22acec8)[0]) == b'uin'
        assert imports[0x4b098b8] == b'napi_create_string_utf8'
        assert imports[0x4b09980] == b'napi_set_named_property'
    finally:
        pe.close()

    repo = Path(__file__).resolve().parents[3]
    pins = json.loads((repo/'scripts/qq_napcat_runtime_pins.json').read_text('utf8'))['napcatPatch']
    raw = (repo/'runtime/qq-napcat-candidate/napcat.mjs').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pins['patchedSha256']
    source = raw.decode('utf8')
    for change in reversed(pins['replacements']):
        assert source.count(change['replacement']) == 1
        source = source.replace(change['replacement'], change['anchor'], 1)
    assert hashlib.sha256(source.encode('utf8')).hexdigest() == pins['upstreamSha256']
    # Semantics still require actual runtime corroboration in normal desktop QQ.
    return {'dispatch': records, 'registration_to_js_reference_verified': True,
            'success_uin_object_offset': 48, 'success_uin_native_type': 'uint64',
            'reference_upstream_sha256': pins['upstreamSha256'],
            'runtime_identity_proven': False, 'qq_process_accessed': False}


if __name__ == '__main__':
    try:
        print(json.dumps(check()))
    except Exception:
        print(json.dumps({'reason': 'login_source_evidence_refused', 'qq_process_accessed': False}))
        raise SystemExit(1)
