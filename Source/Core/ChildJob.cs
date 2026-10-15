using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// Ties every command the window starts to the window itself. A wrapper is a cmd that starts
/// PowerShell, which starts rclone or ssh: STOP and a closing window end that tree by hand, but a
/// window that fell would leave an upload running with nobody to watch it. A job object set to
/// "kill on close" is closed by Windows with the last process that holds it - this one - and
/// takes the tree with it.
///
/// Only the commands are put into the job, not the window: a file or a folder the window opens in
/// another program must stay open after the window is gone.
///
/// The job lets a process out when the one that starts it asks for that (breakaway): a command
/// that leaves a tool running on purpose - WinUtil in a terminal of its own - starts it so, and
/// the tool outlives STOP of a later run and the window. Nothing leaves that did not ask.
/// </summary>
public static class ChildJob
{
    const int ExtendedLimitInformation = 9;
    const uint KillOnJobClose = 0x2000;
    const uint BreakawayOk = 0x0800;

    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters
    {
        public ulong ReadOperations, WriteOperations, OtherOperations, ReadTransfer, WriteTransfer, OtherTransfer;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits
    {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateJobObject(IntPtr security, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimits info, uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool TerminateJobObject(IntPtr job, uint exitCode);

    static readonly object Gate = new();
    static IntPtr _job;
    static bool _failed;

    /// <summary>The job is there, or could be made.</summary>
    static bool Ready()
    {
        lock (Gate)
        {
            if (_job != IntPtr.Zero) return true;
            if (_failed) return false;
            var job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) { _failed = true; return false; }
            var limits = new ExtendedLimits();
            limits.Basic.LimitFlags = KillOnJobClose | BreakawayOk;
            if (!SetInformationJobObject(job, ExtendedLimitInformation, ref limits, (uint)Marshal.SizeOf<ExtendedLimits>())) { _failed = true; return false; }
            _job = job;
            return true;
        }
    }

    /// <summary>
    /// Puts a command just started into the job; whatever it starts later is born inside. False
    /// when Windows refused - the caller says so once, and STOP still ends the tree by hand.
    /// </summary>
    public static bool Hold(Process process)
    {
        try { return Ready() && AssignProcessToJobObject(_job, process.Handle); }
        catch { return false; }
    }

    /// <summary>
    /// Ends every process the job holds - the command and all it started, whoever their parent
    /// was: a process whose parent is gone already is not found by a walk down the tree, and the
    /// job still holds it. The job itself stays, for the next command. The exit code is the one
    /// a process ended by hand has, -1.
    /// </summary>
    public static void EndAll()
    {
        IntPtr job;
        lock (Gate) job = _job;
        if (job != IntPtr.Zero) TerminateJobObject(job, 0xFFFFFFFF);
    }
}
