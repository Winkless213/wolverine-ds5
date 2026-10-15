param(
    [Parameter(Mandatory)][string]$InstanceId,
    [switch]$Install,
    [switch]$Restore
)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class WinUsbSwap {
    [StructLayout(LayoutKind.Sequential)]
    public struct SP_DEVINFO_DATA { public uint cbSize; public Guid ClassGuid; public uint DevInst; public IntPtr Reserved; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct SP_DEVINSTALL_PARAMS {
        public uint cbSize; public uint Flags; public uint FlagsEx; public IntPtr hwndParent;
        public IntPtr InstallMsgHandler; public IntPtr InstallMsgHandlerContext; public IntPtr FileQueue;
        public IntPtr ClassInstallReserved; public uint Reserved;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string DriverPath;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct SP_DRVINFO_DATA {
        public uint cbSize; public uint DriverType; public IntPtr Reserved;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string Description;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string MfgName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string ProviderName;
        public long DriverDate; public ulong DriverVersion;
    }

    [DllImport("setupapi.dll", SetLastError = true)]
    static extern IntPtr SetupDiCreateDeviceInfoList(IntPtr classGuid, IntPtr hwnd);
    [DllImport("setupapi.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetupDiOpenDeviceInfo(IntPtr set, string id, IntPtr hwnd, uint flags, ref SP_DEVINFO_DATA dev);
    [DllImport("setupapi.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetupDiGetDeviceInstallParams(IntPtr set, ref SP_DEVINFO_DATA dev, ref SP_DEVINSTALL_PARAMS p);
    [DllImport("setupapi.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetupDiSetDeviceInstallParams(IntPtr set, ref SP_DEVINFO_DATA dev, ref SP_DEVINSTALL_PARAMS p);
    [DllImport("setupapi.dll", SetLastError = true)]
    static extern bool SetupDiBuildDriverInfoList(IntPtr set, ref SP_DEVINFO_DATA dev, uint type);
    [DllImport("setupapi.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetupDiEnumDriverInfo(IntPtr set, ref SP_DEVINFO_DATA dev, uint type, uint index, ref SP_DRVINFO_DATA drv);
    [DllImport("setupapi.dll", SetLastError = true)]
    static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
    [DllImport("newdev.dll", SetLastError = true)]
    static extern bool DiInstallDevice(IntPtr hwnd, IntPtr set, ref SP_DEVINFO_DATA dev, ref SP_DRVINFO_DATA drv, uint flags, out bool reboot);

    const uint DI_ENUMSINGLEINF = 0x00010000, DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x00000800, SPDIT_CLASSDRIVER = 1, SPDIT_COMPATDRIVER = 2;

    static void Check(bool ok, string what) {
        if (!ok) { int e = Marshal.GetLastWin32Error(); throw new Exception(what + " failed: 0x" + e.ToString("X") + " " + new System.ComponentModel.Win32Exception(e).Message); }
    }

    public static string Run(string id, string inf, bool install) {
        IntPtr set = SetupDiCreateDeviceInfoList(IntPtr.Zero, IntPtr.Zero);
        try {
            var dev = new SP_DEVINFO_DATA(); dev.cbSize = (uint)Marshal.SizeOf(dev);
            Check(SetupDiOpenDeviceInfo(set, id, IntPtr.Zero, 0, ref dev), "SetupDiOpenDeviceInfo");
            var p = new SP_DEVINSTALL_PARAMS(); p.cbSize = (uint)Marshal.SizeOf(p);
            Check(SetupDiGetDeviceInstallParams(set, ref dev, ref p), "SetupDiGetDeviceInstallParams");
            p.DriverPath = inf; p.Flags |= DI_ENUMSINGLEINF; p.FlagsEx |= DI_FLAGSEX_ALLOWEXCLUDEDDRVS;
            Check(SetupDiSetDeviceInstallParams(set, ref dev, ref p), "SetupDiSetDeviceInstallParams");
            Check(SetupDiBuildDriverInfoList(set, ref dev, SPDIT_CLASSDRIVER), "SetupDiBuildDriverInfoList");
            string found = "device class: " + dev.ClassGuid + "\n";
            for (uint i = 0; ; i++) {
                var drv = new SP_DRVINFO_DATA(); drv.cbSize = (uint)Marshal.SizeOf(drv);
                if (!SetupDiEnumDriverInfo(set, ref dev, SPDIT_CLASSDRIVER, i, ref drv)) break;
                found += string.Format("[{0}] {1} | {2} | {3}\n", i, drv.Description, drv.MfgName, drv.ProviderName);
                // Description is localized per process language: an interactive admin shell gets
                // "WinUsb Device" while the tray app's ShellExecuteEx-elevated process gets the
                // zh-CN form, so an equality test never matches there. Only the WinUSB model keeps
                // the "WinUSB" token in every language; Billboard and ADB never contain it.
                // Keep this here-string ASCII-only: the .ps1 has no BOM, so Windows PowerShell 5.1
                // decodes it as ANSI and any non-ASCII byte corrupts the C# source below.
                if (install && drv.Description.IndexOf("winusb", StringComparison.OrdinalIgnoreCase) >= 0) {
                    bool reboot;
                    Check(DiInstallDevice(IntPtr.Zero, set, ref dev, ref drv, 0, out reboot), "DiInstallDevice");
                    return found + "installed, reboot required: " + reboot;
                }
            }
            return found + "no WinUsb Device";
        } finally { SetupDiDestroyDeviceInfoList(set); }
    }

    // Way back to the stock Xbox driver: rank by hardware/compatible ID and install the best
    // match. Ranking, not a description test, picks the model -- the receiver matches
    // USB\MS_COMP_XGIP10 in dc1-controller.inf, and descriptions are localized per process
    // language so they are not a stable key. Leaves the device node alone; unlike
    // "pnputil /remove-device" + "/scan-devices" this cannot strand the wireless receiver.
    public static string Restore(string id) {
        IntPtr set = SetupDiCreateDeviceInfoList(IntPtr.Zero, IntPtr.Zero);
        try {
            var dev = new SP_DEVINFO_DATA(); dev.cbSize = (uint)Marshal.SizeOf(dev);
            Check(SetupDiOpenDeviceInfo(set, id, IntPtr.Zero, 0, ref dev), "SetupDiOpenDeviceInfo");
            Check(SetupDiBuildDriverInfoList(set, ref dev, SPDIT_COMPATDRIVER), "SetupDiBuildDriverInfoList");
            var drv = new SP_DRVINFO_DATA(); drv.cbSize = (uint)Marshal.SizeOf(drv);
            if (!SetupDiEnumDriverInfo(set, ref dev, SPDIT_COMPATDRIVER, 0, ref drv)) return "no compatible driver";
            bool reboot;
            Check(DiInstallDevice(IntPtr.Zero, set, ref dev, ref drv, 0, out reboot), "DiInstallDevice");
            return string.Format("best: {0} | {1}\ninstalled, reboot required: {2}", drv.Description, drv.ProviderName, reboot);
        } finally { SetupDiDestroyDeviceInfoList(set); }
    }
}
'@
$key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$InstanceId"
$before = '{05f5cfe2-4733-4950-a6bb-07aad01a3a84}'
"class before: $before"
try {
    if ($Install) { & "$PSScriptRoot\set_class.ps1" -InstanceId $InstanceId -ClassGuid '{88BAE032-5A81-49f0-BC3D-A4FF138216D6}' }
    if ($Restore) { & "$PSScriptRoot\set_class.ps1" -InstanceId $InstanceId -ClassGuid $before }
    $out = if ($Restore) { [WinUsbSwap]::Restore($InstanceId) }
           else { [WinUsbSwap]::Run($InstanceId, "$env:WINDIR\INF\winusb.inf", $Install.IsPresent) }
    $out
    if (($Install -or $Restore) -and $out -notmatch 'installed') {
        if ($Restore) { throw 'Xbox driver not offered' } else { throw 'WinUsb Device not offered' }
    }
} catch {
    if ($Install) { & "$PSScriptRoot\set_class.ps1" -InstanceId $InstanceId -ClassGuid $before; "class restored: $before" }
    throw
}
