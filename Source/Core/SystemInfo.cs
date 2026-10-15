using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace AudionOfficeOcrAi.Core;

/// <summary>A part of the machine for the header: the few words of the badge, and the whole of it for the tooltip.</summary>
public sealed record Badge(string Text, string Tip, bool Warn = false);

/// <summary>
/// The machine for the header of the window, badge by badge: Windows (edition, version, build,
/// architecture), the computer or its board, the processor, every video card with the version of
/// its driver, the memory, the drives. Read from the registry and
/// Windows itself - no PowerShell, no WMI - so it is there the moment the window opens.
/// </summary>
public static class SystemInfo
{
    [DllImport("kernel32.dll")]
    static extern bool GetPhysicallyInstalledSystemMemory(out ulong kilobytes);

    [DllImport("kernel32.dll")]
    static extern uint GetSystemFirmwareTable(uint provider, uint id, byte[]? buffer, uint size);

    static string Reg(string key, string name) => Registry.GetValue(key, name, null)?.ToString()?.Trim() ?? "";

    static string Squeeze(string text) => Regex.Replace(text, @"\s+", " ").Trim();

    /// <summary>A name of hardware as its maker wrote it, without the marks of a trade mark.</summary>
    static string Bare(string name) => Squeeze(Regex.Replace(name, @"\((R|TM|C)\)|®|™", "", RegexOptions.IgnoreCase));

    // ------------------------------------------------------------ Windows

    public static Badge? Windows(bool ru)
    {
        const string nt = @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion";
        var product = Reg(nt, "ProductName");
        if (product.Length == 0) return null;
        var build = Reg(nt, "CurrentBuild");
        var ubr = Registry.GetValue(nt, "UBR", null) is int u ? $".{u}" : "";
        // Windows 11 still calls itself "Windows 10" in ProductName: the build tells (22000 and up).
        if (int.TryParse(build, out var b) && b >= 22000) product = product.Replace("Windows 10", "Windows 11");
        var version = Reg(nt, "DisplayVersion");
        var bits = RuntimeInformation.OSArchitecture switch
        {
            Architecture.X64 => "x64", Architecture.Arm64 => "ARM64", Architecture.X86 => "x86",
            var other => other.ToString(),
        };
        var text = $"{product}{(version.Length > 0 ? " " + version : "")} · {build}{ubr} · {bits}";
        return new Badge(text, ru
            ? $"Windows этой машины\nИздание: {product}\nВерсия: {version}\nСборка: {build}{ubr}\nРазрядность: {bits}"
            : $"Windows of this machine\nEdition: {product}\nVersion: {version}\nBuild: {build}{ubr}\nArchitecture: {bits}");
    }

    // ------------------------------------------------------------ the computer, its board, its BIOS

    static readonly Regex Unsaid = new(
        @"^$|^(system product name|system manufacturer|system version|to be filled by o\.?e\.?m\.?|default string|not applicable|none|invalid|o\.?e\.?m\.?|n/?a|unknown|type1family0?|sku)$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    static string Said(string value) => Unsaid.IsMatch(value.Trim()) ? "" : Squeeze(value);

    /// <summary>The maker by the name people know it by: "ASUSTeK COMPUTER INC." is ASUS.</summary>
    static string Maker(string name)
    {
        if (name.Length == 0) return "";
        foreach (var (pattern, known) in new[]
        {
            ("asustek|^asus", "ASUS"), ("micro-star|^msi", "MSI"), ("gigabyte", "Gigabyte"), ("^lenovo", "Lenovo"),
            ("^dell", "Dell"), ("hewlett|^hp\\b", "HP"), ("^acer", "Acer"), ("asrock", "ASRock"), ("^microsoft", "Microsoft"),
            ("^samsung", "Samsung"), ("^huawei", "Huawei"), ("^intel", "Intel"), ("^apple", "Apple"), ("^razer", "Razer"),
            ("^xiaomi|^timi", "Xiaomi"), ("^honor", "HONOR"), ("^biostar", "Biostar"), ("^supermicro", "Supermicro"),
        })
            if (Regex.IsMatch(name, pattern, RegexOptions.IgnoreCase)) return known;
        return Squeeze(Regex.Replace(name, @",?\s*\b(inc|co|ltd|corp|corporation|company|computer|technology|international|electronics)\b\.?", "", RegexOptions.IgnoreCase)).TrimEnd(',', '.', ' ');
    }

    /// <summary>The computer by its model, or - a desktop put together by hand - by its board; the BIOS in the tooltip.</summary>
    public static Badge? Machine(bool ru)
    {
        const string bios = @"HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\BIOS";
        string maker = Said(Reg(bios, "SystemManufacturer")), product = Said(Reg(bios, "SystemProductName"));
        string family = Said(Reg(bios, "SystemFamily")), systemVersion = Said(Reg(bios, "SystemVersion"));
        string boardMaker = Said(Reg(bios, "BaseBoardManufacturer")), board = Said(Reg(bios, "BaseBoardProduct"));
        string biosVersion = Said(Reg(bios, "BIOSVersion")), biosDate = Said(Reg(bios, "BIOSReleaseDate")), biosVendor = Said(Reg(bios, "BIOSVendor"));

        // Lenovo writes the name people know in the version ("ThinkPad X1 Carbon Gen 10") and a type number in the product.
        string model = Maker(maker) == "Lenovo" && systemVersion.Length > 0 ? systemVersion : product;
        string name = model.Length > 0 ? model : board;
        string by = Maker(model.Length > 0 && maker.Length > 0 ? maker : boardMaker.Length > 0 ? boardMaker : maker);
        if (name.Length == 0) return null;
        var text = by.Length > 0 && !name.StartsWith(by, StringComparison.OrdinalIgnoreCase) ? by + " " + name : name;

        var tip = new List<string> { ru ? "Компьютер" : "The computer" };
        void Line(string ruName, string enName, params string[] parts)
        {
            var value = Squeeze(string.Join(" ", parts.Where(part => part.Length > 0))).Replace(" )", ")");
            if (value.Length > 0) tip.Add((ru ? ruName : enName) + ": " + value);
        }
        Line("Модель", "Model", maker, product);
        if (systemVersion.Length > 0 && systemVersion != product) Line("Название", "Name", systemVersion);
        if (family.Length > 0 && family != product && family != systemVersion) Line("Семейство", "Family", family);
        // A notebook names its board as it names itself: said once.
        if (board != product) Line("Плата", "Board", boardMaker, board);
        Line("BIOS", "BIOS", biosVendor, biosVersion, biosDate.Length > 0 ? (ru ? "от " : "of ") + Date(biosDate) : "");
        return new Badge(text, string.Join("\n", tip));
    }

    /// <summary>A date the registry holds the American way - 03/27/2024, 8-14-2024 - as it is written here.</summary>
    static string Date(string american)
    {
        foreach (var format in new[] { "M/d/yyyy", "M-d-yyyy", "MM/dd/yyyy", "MM-dd-yyyy", "yyyy-MM-dd", "yyyyMMdd" })
            if (DateTime.TryParseExact(american, format, CultureInfo.InvariantCulture, DateTimeStyles.None, out var date))
                return date.ToString("dd.MM.yyyy", CultureInfo.InvariantCulture);
        return american;
    }

    // ------------------------------------------------------------ the processor

    public static Badge? Processor(bool ru)
    {
        var full = Squeeze(Reg(@"HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString"));
        if (full.Length == 0) return null;
        // "12th Gen Intel(R) Core(TM) i5-1245U", "AMD Ryzen 7 5800X 8-Core Processor", "... CPU @ 2.50GHz": the name
        // with its generation (the owner, 10.10.2026: "keep 12th Gen"), without the marks and the tail.
        var text = Bare(full);
        text = Regex.Replace(text, @"\s+CPU\b|\s*@\s*[\d.]+\s*GHz|\s+\d+-Core Processor|\s+Processor\b|\s+with Radeon.*$", "", RegexOptions.IgnoreCase);
        int threads = Environment.ProcessorCount;
        return new Badge(Squeeze(text), ru
            ? $"Процессор\n{full}\nЛогических процессоров: {threads}"
            : $"The processor\n{full}\nLogical processors: {threads}");
    }

    // ------------------------------------------------------------ the video cards and their drivers

    /// <summary>
    /// Real video cards from the display class of the registry - virtual and basic adapters left
    /// out - each with its driver: the version the maker names it by where it differs from the one
    /// Windows holds (NVIDIA 32.0.15.6094 is 560.94), the full one and its date in the tooltip.
    /// </summary>
    public static IReadOnlyList<Badge> VideoCards(bool ru)
    {
        var cards = new List<Badge>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using var cls = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}");
        if (cls is null) return cards;
        foreach (var sub in cls.GetSubKeyNames().Where(n => n.Length == 4 && n.All(char.IsDigit)))
        {
            using var key = cls.OpenSubKey(sub);
            var name = key?.GetValue("DriverDesc")?.ToString()?.Trim() ?? "";
            if (name.Length == 0 || !seen.Add(name)) continue;
            if (Regex.IsMatch(name, @"basic display|basic render|virtual|parsec|remote|indirect|citrix|vmware|hyper-v|mirror", RegexOptions.IgnoreCase)) continue;
            string version = key?.GetValue("DriverVersion")?.ToString()?.Trim() ?? "";
            string date = Date(key?.GetValue("DriverDate")?.ToString()?.Trim() ?? "");
            string provider = key?.GetValue("ProviderName")?.ToString()?.Trim() ?? "";
            string radeon = key?.GetValue("RadeonSoftwareVersion")?.ToString()?.Trim() ?? "";
            string known = Regex.IsMatch(name, "nvidia", RegexOptions.IgnoreCase) ? NvidiaVersion(version) : radeon;
            string shown = known.Length > 0 ? known : version;

            var text = Bare(name) + (shown.Length > 0 ? (ru ? " · драйвер " : " · driver ") + shown : "");
            var tip = new List<string> { ru ? "Видеокарта" : "A video card", name };
            if (version.Length > 0)
                tip.Add((ru ? "Драйвер: " : "Driver: ") + (known.Length > 0 ? $"{known} ({version})" : version) + (date.Length > 0 ? (ru ? " от " : " of ") + date : ""));
            if (provider.Length > 0) tip.Add((ru ? "Поставщик драйвера: " : "Driver provider: ") + provider);
            cards.Add(new Badge(text, string.Join("\n", tip)));
        }
        return cards;
    }

    /// <summary>NVIDIA names a driver by the last five digits of the version Windows holds: 32.0.15.6094 is 560.94.</summary>
    static string NvidiaVersion(string windows)
    {
        var digits = string.Concat(windows.Split('.').TakeLast(2)).Where(char.IsDigit).ToArray();
        if (digits.Length < 5) return "";
        var last = new string(digits[^5..]);
        return last[..3].TrimStart('0') + "." + last[3..];
    }

    // ------------------------------------------------------------ the memory

    public static Badge? Memory(bool ru)
    {
        if (!GetPhysicallyInstalledSystemMemory(out var kb) || kb == 0) return null;
        var type = MemoryType();
        var size = $"{Math.Round(kb / 1024.0 / 1024.0)} {(ru ? "ГБ" : "GB")}";
        return new Badge(size + (type.Length > 0 ? " " + type : ""), ru
            ? $"Оперативная память\nУстановлено: {size}" + (type.Length > 0 ? $"\nТип: {type}" : "")
            : $"The memory\nInstalled: {size}" + (type.Length > 0 ? $"\nType: {type}" : ""));
    }

    /// <summary>
    /// DDR generation from the SMBIOS table (Memory Device, type 17): the first populated slot tells.
    /// Empty string when the firmware does not say.
    /// </summary>
    public static string MemoryType()
    {
        const uint rsmb = 0x52534D42; // 'RSMB'
        var size = GetSystemFirmwareTable(rsmb, 0, null, 0);
        if (size == 0) return "";
        var raw = new byte[size];
        if (GetSystemFirmwareTable(rsmb, 0, raw, size) != size) return "";
        int pos = 8, end = 8 + (int)BitConverter.ToUInt32(raw, 4);
        end = Math.Min(end, raw.Length);
        while (pos + 4 <= end)
        {
            int kind = raw[pos], len = raw[pos + 1];
            if (kind == 127 || len < 4) break;
            if (kind == 17 && len > 0x12 && pos + 0x12 < end)
            {
                var slot = BitConverter.ToUInt16(raw, pos + 0x0C);
                if (slot != 0 && slot != 0xFFFF)
                {
                    var name = raw[pos + 0x12] switch
                    {
                        0x18 => "DDR3", 0x1A => "DDR4", 0x1B => "LPDDR", 0x1C => "LPDDR2", 0x1D => "LPDDR3",
                        0x1E => "LPDDR4", 0x22 => "DDR5", 0x23 => "LPDDR5", _ => "",
                    };
                    if (name.Length > 0) return name;
                }
            }
            // Past the formatted part, then past the strings that end with two zero bytes.
            pos += len;
            while (pos + 1 < end && !(raw[pos] == 0 && raw[pos + 1] == 0)) pos++;
            pos += 2;
        }
        return "";
    }

    // ------------------------------------------------------------ the drives

    /// <summary>The drive Windows lives on - usually C:, but not always.</summary>
    public static string SystemDrive => Path.GetPathRoot(Environment.SystemDirectory) ?? "C:\\";

    /// <summary>A drive by how much of it is free. Asked again after every run: a download takes its room.</summary>
    public static Badge? Drive(string root, bool ru, bool downloads)
    {
        try
        {
            var drive = new DriveInfo(root);
            if (!drive.IsReady) return null;
            string unit = ru ? "ГБ" : "GB", letter = drive.Name.TrimEnd('\\');
            string Gb(long bytes) => Math.Round(bytes / 1024.0 / 1024 / 1024).ToString(CultureInfo.InvariantCulture);
            string free = Gb(drive.AvailableFreeSpace), all = Gb(drive.TotalSize);
            var text = ru ? $"{letter} свободно {free} из {all} {unit}" : $"{letter} {free} of {all} {unit} free";
            var what = downloads ? (ru ? "Диск назначения" : "The drive of the target") : (ru ? "Системный диск" : "The system drive");
            var label = drive.VolumeLabel is { Length: > 0 } named ? $" «{named}»" : "";
            return new Badge(text, ru
                ? $"{what} ({letter}){label}\nВсего: {all} {unit}\nСвободно: {free} {unit}\nФайловая система: {drive.DriveFormat}"
                : $"{what} ({letter}){label}\nSize: {all} {unit}\nFree: {free} {unit}\nFile system: {drive.DriveFormat}",
                // A run copies the source into input, writes output and copies it to the target: three times its size.
                Warn: drive.AvailableFreeSpace < 10L * 1024 * 1024 * 1024);
        }
        catch { return null; }
    }
}
