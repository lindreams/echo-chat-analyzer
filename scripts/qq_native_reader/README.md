# QQ 只读数据库组件

读取器适配器和导出表见 `reader.c`、`reader.def`。SQLCipher 源码固定为
`f049bed66ca26741f09a6e4f0603ed3af195ac96`，源码归档 SHA-256 为
`53c3faf8dddae330a929adae26311a038881ca06b4434c59d208d2c3e71d46`。
`sqlcipher-read-only.patch` 对应该提交上用于读取器的两处源文件修改。

在 Windows x64 构建中定义 `ECHO_QQ_SNAPSHOT_READER=1`，保持 `SQLITE_UNTESTABLE`，
启用 OpenSSL 后端的内存清理和锁定。`echo_pending_byte()` 仅返回此构建的
`PENDING_BYTE`。应用隔离读取进程负责密钥和源文件的校验，读取器只打开只读连接。

应用启动读取时按 `src/qq_chat_analyzer/providers/qq_independent/native-pins.json`
校验读取器及其加密依赖。Windows 打包脚本和 Setup 打包器也核对相同指纹。
SQLCipher 和 OpenSSL 许可位于 `third_party/`，并随安装包分发。

加密依赖来自 OpenSSL `3.5.9` 源码归档，SHA-256 为
`603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a`。
使用 Windows x64 MinGW-w64 UCRT GCC 14.2.0，在 MSYS 环境中执行
`perl Configure mingw64 no-tests no-apps no-docs` 和 `make build_libs`。
打包只取 `libcrypto-3-x64.dll`。运行时加载目录由应用指定。
