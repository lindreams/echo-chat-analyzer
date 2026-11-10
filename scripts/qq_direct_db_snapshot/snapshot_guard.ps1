# Pin only an owned, published snapshot. No source database is opened here.
$ErrorActionPreference = 'Stop'
try {
    [Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    $request = [Console]::ReadLine() | ConvertFrom-Json
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class EchoSnapshotGuard {
    [StructLayout(LayoutKind.Sequential)] struct Info {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
    static string Identity(FileStream stream) {
        Info info;
        if(!GetFileInformationByHandle(stream.SafeFileHandle,out info) || info.Links!=1 ||
           (info.Attributes & (0x400u | 0x10u))!=0) throw new IOException();
        return (((ulong)info.IndexHigh<<32)|info.IndexLow).ToString();
    }
    public static void Run(string database,string manifest) {
        // FileShare.Read prevents writes, replacement and deletion through any
        // hard link. Existing incompatible writers make this open fail closed.
        using(var db=new FileStream(database,FileMode.Open,FileAccess.Read,FileShare.Read))
        using(var mf=new FileStream(manifest,FileMode.Open,FileAccess.Read,FileShare.Read)) {
            var clock=Stopwatch.StartNew();
            Console.WriteLine(Identity(db)+":"+Identity(mf)); Console.Out.Flush();
            while(true) {
                // Independent bound also releases handles after a lost consumer.
                int remaining=900000-(int)clock.ElapsedMilliseconds;
                if(remaining<=0) throw new IOException();
                var read=System.Threading.Tasks.Task.Run(()=>Console.In.ReadLine());
                if(!read.Wait(remaining)) throw new IOException();
                string line=read.Result;
                if(line==null || line=="release") break;
                if(line!="check") throw new IOException();
                Console.WriteLine(Identity(db)+":"+Identity(mf)); Console.Out.Flush();
            }
        }
        Console.WriteLine("released"); Console.Out.Flush();
    }
}
'@
    [EchoSnapshotGuard]::Run([string]$request.database,[string]$request.manifest)
} catch {
    [Console]::WriteLine('failed')
    exit 1
}
