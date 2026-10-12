param([Parameter(Mandatory)][string]$InstanceId, [Parameter(Mandatory)][string]$ClassGuid)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CmClass {
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    static extern uint CM_Locate_DevNodeW(out uint devinst, string id, uint flags);
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    static extern uint CM_Set_DevNode_Registry_PropertyW(uint devinst, uint prop, byte[] buf, uint len, uint flags);
    public static string Set(string id, string guid) {
        uint dn; uint r = CM_Locate_DevNodeW(out dn, id, 0);
        if (r != 0) return "locate CR=0x" + r.ToString("X");
        byte[] b = System.Text.Encoding.Unicode.GetBytes(guid + "\0");
        r = CM_Set_DevNode_Registry_PropertyW(dn, 0x9, b, (uint)b.Length, 0);
        return "set class CR=0x" + r.ToString("X");
    }
}
'@
[CmClass]::Set($InstanceId, $ClassGuid)
