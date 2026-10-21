param([Parameter(Mandatory)][string]$InstanceId, [Parameter(Mandatory)][string]$ClassGuid, [switch]$AllowAbsent)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CmClass {
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    static extern uint CM_Locate_DevNodeW(out uint devinst, string id, uint flags);
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    static extern uint CM_Set_DevNode_Registry_PropertyW(uint devinst, uint prop, byte[] buf, uint len, uint flags);
    public static string Set(string id, string guid, bool allowAbsent) {
        uint dn; uint r = CM_Locate_DevNodeW(out dn, id, allowAbsent ? 1u : 0u);
        if (r != 0) throw new InvalidOperationException("locate CR=0x" + r.ToString("X"));
        byte[] b = System.Text.Encoding.Unicode.GetBytes(guid + "\0");
        r = CM_Set_DevNode_Registry_PropertyW(dn, 0x9, b, (uint)b.Length, 0);
        if (r != 0) throw new InvalidOperationException("set class CR=0x" + r.ToString("X"));
        return "set class CR=0x0";
    }
}
'@
[CmClass]::Set($InstanceId, $ClassGuid, $AllowAbsent.IsPresent)
