using Microsoft.PowerShell;

namespace AudionOfficeOcrAi.Ps;

/// <summary>
/// pwsh under the program's name: the same arguments (-NoProfile, -File, -Command...), the same
/// console host, the engine pinned by the package. Nothing of its own - a script or a wrapper that
/// worked with pwsh.exe works with this file unchanged.
/// </summary>
static class Program
{
    static int Main(string[] args) => UnmanagedPSEntry.Start(args, args.Length);
}
