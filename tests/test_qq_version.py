"""Synthetic Windows version API shared by the launch-gate tests."""


import ctypes
import importlib
import importlib.util


def _module():
    name = "qq_chat_analyzer.application.qq.qq_version"
    assert importlib.util.find_spec(name) is not None, "QQ executable version reader is missing"
    return importlib.import_module(name)


class _FixedInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "signature", "structure_version", "file_ms", "file_ls", "product_ms",
        "product_ls", "flags_mask", "flags", "os", "file_type", "subtype", "date_ms", "date_ls",
    )]


class _Function:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


class _VersionApi:
    def __init__(self, file_version=(9, 9, 15, 27597), product_version=None, fault=None):
        product_version = file_version if product_version is None else product_version
        self.info = _FixedInfo()
        self.info.signature = 0 if fault == "signature" else 0xFEEF04BD
        self.info.file_type = 1
        self.info.file_ms = (file_version[0] << 16) | file_version[1]
        self.info.file_ls = (file_version[2] << 16) | file_version[3]
        self.info.product_ms = (product_version[0] << 16) | product_version[1]
        self.info.product_ls = (product_version[2] << 16) | product_version[3]
        self.fault = fault
        self.paths = []
        self.GetFileVersionInfoSizeW = _Function(self.size)
        self.GetFileVersionInfoW = _Function(self.read)
        self.VerQueryValueW = _Function(self.query)

    def size(self, path, handle):
        self.paths.append(path)
        return 0 if self.fault == "size" else 80

    def read(self, path, handle, size, buffer):
        assert path == self.paths[0]
        assert handle == 0 and size == 80
        ctypes.memmove(ctypes.addressof(buffer) + 8, ctypes.byref(self.info), 52)
        return self.fault != "read"

    def query(self, buffer, key, pointer, length):
        assert key == "\\"
        address = ctypes.addressof(buffer) + 8
        if self.fault == "pointer":
            address = ctypes.addressof(buffer) + 80
        if self.fault == "null":
            address = 0
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = address
        ctypes.cast(length, ctypes.POINTER(ctypes.c_uint))[0] = 1 if self.fault == "length" else 52
        return self.fault != "query"
