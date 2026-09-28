using System.Collections;
using System.Buffers.Binary;
using System.Security.Cryptography;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Versions;
using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.UnrealTypes;

const string ExpectedBuild = "d8d320363be69ea9dfb39b5c20c8de5237c642841fe3ac86b00f8115050fe06e";
const string Usage = "Usage: NativeSettingsAssetWriter inspect-ui <pinned-candidate.uasset>\n       NativeSettingsAssetWriter roundtrip <input.uasset> <new-output.uasset>\n       NativeSettingsAssetWriter replace-text <input.uasset> <new-output.uasset> <text-id> <expected-source> <replacement>\n       NativeSettingsAssetWriter add-text <input.uasset> <new-output.uasset> <new-text-id> <source-string>\n       NativeSettingsAssetWriter extract-iggy <input.uasset> <new-output.iggy>\n       NativeSettingsAssetWriter replace-iggy <input.uasset> <new-output.uasset> <validated.iggy>";
var iggyAssetAllowlist = new Dictionary<string, string>(StringComparer.Ordinal)
{
    [ExpectedBuild] = "settings",
    ["941e57905b698214e7e962a613e486ef512eaa0a48ba09f40abbf1522f58cd70"] = "character",
    ["9e4454e8ddfd417a83c1995e48eaaed4a114e5e95808039f2decbb0342bec001"] = "community",
    ["00b46a42a6fc83645ace9f7068b8fc3b34ed7c9abd0c185580abbfb5a7d53ab6"] = "pause",
    ["9875c79a3afd5c0cd5ef4c9c5df91e55e5f069cb0ab97d9ce161a59fbf80b5cc"] = "hud",
    ["f91806d92ea18b12440bb0117d012fb20d3f9ab472c2841ab95d858083319945"] = "map",
};
var iggyReplaceAllowlist = new Dictionary<string, string>(StringComparer.Ordinal)
{
    [ExpectedBuild] = "settings",
    ["941e57905b698214e7e962a613e486ef512eaa0a48ba09f40abbf1522f58cd70"] = "character",
    ["9e4454e8ddfd417a83c1995e48eaaed4a114e5e95808039f2decbb0342bec001"] = "community",
};
var uiInspectionAllowlist = new Dictionary<string, string>(StringComparer.Ordinal)
{
    ["9875c79a3afd5c0cd5ef4c9c5df91e55e5f069cb0ab97d9ce161a59fbf80b5cc"] = "Art/UI/hud.uasset",
    ["f91806d92ea18b12440bb0117d012fb20d3f9ab472c2841ab95d858083319945"] = "Art/UI/map.uasset",
    ["9094006c243e964ded98e4e08d4697b8ca15c0b1b2c47c6fef5bd382e00f6fb2"] = "Art/UI/character_manager.uasset",
};

try
{
    var inspectOnly = args.Length == 2 && args[0] == "inspect-ui";
    if (!inspectOnly && (args.Length < 3 || args.Length > 6 ||
        (args[0] == "roundtrip" && args.Length != 3) ||
        (args[0] == "replace-text" && args.Length != 6) ||
        (args[0] == "add-text" && args.Length != 5) ||
        (args[0] == "extract-iggy" && args.Length != 3) ||
        (args[0] == "replace-iggy" && args.Length != 4) ||
        (args[0] != "roundtrip" && args[0] != "replace-text" && args[0] != "add-text" && args[0] != "extract-iggy" && args[0] != "replace-iggy")))
    {
        Console.Error.WriteLine(Usage);
        return 2;
    }

    var inputPath = Path.GetFullPath(args[1]);
    var outputPath = inspectOnly ? "" : Path.GetFullPath(args[2]);
    if (!inspectOnly && StringComparer.OrdinalIgnoreCase.Equals(inputPath, outputPath))
        throw new InvalidOperationException("Input and output must be different files; the source asset is never overwritten.");
    if (!inspectOnly && File.Exists(outputPath)) throw new IOException("Output already exists; choose a new path so an earlier result is not overwritten.");

    if (!File.Exists(inputPath)) throw new FileNotFoundException("Input asset not found.", inputPath);

    var inputBytes = File.ReadAllBytes(inputPath);
    var inputHash = Convert.ToHexString(SHA256.HashData(inputBytes)).ToLowerInvariant();
    if (inspectOnly)
    {
        if (!uiInspectionAllowlist.TryGetValue(inputHash, out var candidateAsset))
            throw new InvalidDataException("inspect-ui only accepts the pinned build 16535856 HUD, Map, or Character Manager asset SHA-256.");

        var inspectedAsset = new UAsset(inputPath);
        var iggySignature = new byte[] { 0x49, 0x67, 0x0a, 0xed };
        var iggyExports = inspectedAsset.Exports.OfType<NormalExport>()
            .Where(item => item.Extras is { Length: > 24 } extras && extras.AsSpan(20, 4).SequenceEqual(iggySignature))
            .ToList();
        Console.WriteLine($"PASS inspect-ui: build=16535856; asset={candidateAsset}; sha256={inputHash}; exports={inspectedAsset.Exports.Count}; iggy_exports={iggyExports.Count}");
        foreach (var item in iggyExports)
        {
            var extras = item.Extras!;
            var textCount = item.Data.OfType<ArrayPropertyData>().FirstOrDefault(property => property.Name.ToString() == "TextTable")?.Value.Count() ?? 0;
            var apiCount = item.Data.OfType<ArrayPropertyData>().FirstOrDefault(property => property.Name.ToString() == "ApiFunctions")?.Value.Count() ?? 0;
            Console.WriteLine($"IggyExport={item.ObjectName}; extras={extras.Length}; payload={extras.Length - 20}; TextTable={textCount}; ApiFunctions={apiCount}");
        }
        return 0;
    }

    var exportName = args[0] switch
    {
        "extract-iggy" => iggyAssetAllowlist.TryGetValue(inputHash, out var allowedExtractExport)
            ? allowedExtractExport
            : throw new InvalidDataException("extract-iggy only accepts the pinned build 16535856 settings, character, community, pause, HUD, or map UI assets."),
        "replace-iggy" => iggyReplaceAllowlist.TryGetValue(inputHash, out var allowedReplaceExport)
            ? allowedReplaceExport
            : throw new InvalidDataException("replace-iggy only accepts the pinned build 16535856 settings, character, or community UI assets."),
        _ => StringComparer.Ordinal.Equals(inputHash, ExpectedBuild)
            ? "settings"
            : throw new InvalidDataException("This operation only accepts the pinned build 16535856 settings.uasset SHA-256."),
    };

    var asset = new UAsset(inputPath);
    var export = asset.Exports.OfType<NormalExport>().Single(item => item.ObjectName.ToString() == exportName);
    if (args[0] == "extract-iggy")
    {
        var extras = export.Extras ?? throw new InvalidDataException("The selected UI export has no Iggy payload.");
        const int envelopeSize = 20;
        if (extras.Length <= envelopeSize + 4 ||
            BinaryPrimitives.ReadUInt32LittleEndian(extras.AsSpan(4, 4)) != extras.Length - envelopeSize ||
            BinaryPrimitives.ReadUInt32LittleEndian(extras.AsSpan(8, 4)) != extras.Length - envelopeSize ||
            !extras.AsSpan(envelopeSize, 4).SequenceEqual(new byte[] { 0x49, 0x67, 0x0a, 0xed }) ||
            extras[envelopeSize + 9] != 64)
            throw new InvalidDataException("The export does not contain the expected 20-byte envelope, Iggy signature, and 64-bit platform marker.");

        var iggyBytes = extras.AsSpan(envelopeSize).ToArray();
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        File.WriteAllBytes(outputPath, iggyBytes);
        Console.WriteLine($"PASS extract-iggy: build=16535856; asset={exportName}; payload={iggyBytes.Length} bytes; version=0x{BinaryPrimitives.ReadUInt32LittleEndian(iggyBytes.AsSpan(4, 4)):X}; platform={iggyBytes[8]},{iggyBytes[9]},{iggyBytes[10]},{iggyBytes[11]}");
        Console.WriteLine("Output contains extracted game UI data for local analysis only; do not redistribute it.");
        Console.WriteLine("Output: " + outputPath);
        return 0;
    }

    var table = export.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "TextTable");
    var before = ReadTextTable(table);
    var apiFunctions = export.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "ApiFunctions");
    var apiFunctionCount = apiFunctions.Value.Count();

    string? changedId = null;
    string? addedId = null;
    byte[]? replacementExtras = null;
    if (args[0] == "replace-iggy")
    {
        var payload = File.ReadAllBytes(Path.GetFullPath(args[3]));
        var extras = export.Extras ?? throw new InvalidDataException("Missing original Iggy export payload.");
        if (extras.Length < 52 ||
            BinaryPrimitives.ReadUInt32LittleEndian(extras.AsSpan(4, 4)) != extras.Length - 20 ||
            BinaryPrimitives.ReadUInt32LittleEndian(extras.AsSpan(8, 4)) != extras.Length - 20)
            throw new InvalidDataException("Original Iggy envelope is not the pinned layout.");
        if (payload.Length < 80 || payload.Length > 64 * 1024 * 1024 ||
            !payload.AsSpan(0, 12).SequenceEqual(extras.AsSpan(20, 12)))
            throw new InvalidDataException("Replacement has a different Iggy version/platform or invalid length.");
        var subfileCount = BinaryPrimitives.ReadUInt32LittleEndian(payload.AsSpan(28, 4));
        if (subfileCount != 3) throw new InvalidDataException("Expected the three fixed Iggy subfiles.");
        for (var i = 0; i < subfileCount; i++)
        {
            var entry = payload.AsSpan(32 + i * 16, 16);
            var size = BinaryPrimitives.ReadUInt32LittleEndian(entry.Slice(4, 4));
            var offset = BinaryPrimitives.ReadUInt32LittleEndian(entry.Slice(12, 4));
            if (offset < 80 || (ulong)offset + size > (ulong)payload.Length)
                throw new InvalidDataException("Replacement Iggy subfile exceeds payload bounds.");
        }
        replacementExtras = new byte[20 + payload.Length];
        extras.AsSpan(0, 20).CopyTo(replacementExtras);
        BinaryPrimitives.WriteUInt32LittleEndian(replacementExtras.AsSpan(4, 4), (uint)payload.Length);
        BinaryPrimitives.WriteUInt32LittleEndian(replacementExtras.AsSpan(8, 4), (uint)payload.Length);
        payload.CopyTo(replacementExtras, 20);
        export.Extras = replacementExtras;
    }
    if (args[0] == "replace-text")
    {
        changedId = args[3];
        var rows = before.Where(row => StringComparer.Ordinal.Equals(row.Id, changedId)).ToList();
        if (rows.Count != 1) throw new InvalidDataException($"Expected one TextTable entry with id '{changedId}', found {rows.Count}.");
        if (!StringComparer.Ordinal.Equals(rows[0].Source, args[4]))
            throw new InvalidDataException($"Source text mismatch for '{changedId}'. Expected '{args[4]}', found '{rows[0].Source}'.");

        var rowData = GetStructValues(table.Value.Single(row => StringComparer.Ordinal.Equals(ReadTextRow(row).Id, changedId)));
        var text = rowData.OfType<TextPropertyData>().Single(item => item.Name.ToString() == "Text");
        text.CultureInvariantString = new FString(args[5]);
    }
    else if (args[0] == "add-text")
    {
        addedId = args[3];
        if (before.Any(row => StringComparer.Ordinal.Equals(row.Id, addedId)))
            throw new InvalidDataException($"TextTable already contains id '{addedId}'.");
        if (String.IsNullOrWhiteSpace(addedId) || addedId.Any(character => !(Char.IsAsciiLetterOrDigit(character) || character == '_')))
            throw new ArgumentException("Text id must contain only ASCII letters, digits, and underscores.");

        var template = (PropertyData)table.Value[0].Clone();
        var fields = GetStructValues(template);
        fields.OfType<NamePropertyData>().Single(item => item.Name.ToString() == "Id").Value = FName.FromString(asset, addedId);
        var newText = fields.OfType<TextPropertyData>().Single(item => item.Name.ToString() == "Text");
        newText.Namespace = new FString("Dayton.UI.settings");
        newText.Value = new FString(addedId);
        newText.CultureInvariantString = new FString(args[4]);
        table.Value = table.Value.Append(template).ToArray();
    }

    var outputBytes = asset.WriteData().ToArray();
    Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
    File.WriteAllBytes(outputPath, outputBytes);

    var reparsed = new UAsset(outputPath);
    if (!reparsed.VerifyBinaryEquality()) throw new InvalidDataException("The generated asset does not round-trip byte-for-byte through UAssetAPI.");
    var reparsedExport = reparsed.Exports.OfType<NormalExport>().Single(item => item.ObjectName.ToString() == exportName);
    if (replacementExtras != null && !replacementExtras.AsSpan().SequenceEqual(reparsedExport.Extras))
        throw new InvalidDataException("Replacement Iggy bytes changed during UAsset serialization.");
    var reparsedTable = reparsedExport.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "TextTable");
    var after = ReadTextTable(reparsedTable);
    if (args[0] != "add-text" && before.Count != after.Count)
        throw new InvalidDataException($"TextTable row count changed unexpectedly from {before.Count} to {after.Count}.");
    if (args[0] == "roundtrip")
    {
        if (!inputBytes.AsSpan().SequenceEqual(outputBytes)) throw new InvalidDataException("No-op rebuild changed the asset bytes.");
        if (!before.SequenceEqual(after)) throw new InvalidDataException("No-op rebuild changed TextTable content.");
    }
    else
    {
        var expected = before.Select(row => row.Id == changedId ? row with { Source = args[5] } : row).ToList();
        if (addedId != null) expected.Add(new TextRow(addedId, "Dayton.UI.settings", addedId, args[4]));
        if (!expected.SequenceEqual(after)) throw new InvalidDataException("The edited asset changed TextTable entries outside the requested source string.");
    }
    if (reparsedExport.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "ApiFunctions").Value.Count() != apiFunctionCount)
        throw new InvalidDataException("ApiFunctions count changed unexpectedly.");

    ValidateWithCue4Parse(outputPath, exportName, after.Count);
    Console.WriteLine($"PASS {args[0]}: build=16535856; input={inputBytes.Length} bytes; output={outputBytes.Length} bytes; delta={outputBytes.Length - inputBytes.Length}; TextTable={after.Count}; ApiFunctions={apiFunctionCount}; independent=CUE4Parse UE4.13 package load");
    if (changedId != null) Console.WriteLine($"Changed TextTable[{changedId}] source string only.");
    if (addedId != null) Console.WriteLine($"Added TextTable[{addedId}]. This adds a localization entry only; no visible control or callback is created.");
    Console.WriteLine("Output: " + outputPath);
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine("ERROR: " + error.Message);
    return 1;
}

static List<TextRow> ReadTextTable(ArrayPropertyData table) => table.Value.Select(ReadTextRow).ToList();

static TextRow ReadTextRow(PropertyData row)
{
    var data = GetStructValues(row);
    var id = data.OfType<NamePropertyData>().Single(item => item.Name.ToString() == "Id").Value.ToString();
    var text = data.OfType<TextPropertyData>().Single(item => item.Name.ToString() == "Text");
    return new TextRow(id, text.Namespace?.Value ?? "", text.Value?.Value ?? "", text.CultureInvariantString?.Value ?? "");
}

static IList<PropertyData> GetStructValues(PropertyData row)
{
    var property = row.GetType().GetProperty("Value");
    if (property?.GetValue(row) is IEnumerable values)
        return values.Cast<object>().OfType<PropertyData>().ToList();
    throw new InvalidDataException("Unexpected serialized TextTable row structure: " + row.GetType().FullName);
}

static void ValidateWithCue4Parse(string assetPath, string exportName, int expectedTextRows)
{
    var contentRoot = Path.Combine(Path.GetTempPath(), "sod2-native-settings-cue-" + Guid.NewGuid().ToString("N"), "Content");
    var packagePath = Path.Combine(contentRoot, "Art", "UI", exportName + ".uasset");
    try
    {
        Directory.CreateDirectory(Path.GetDirectoryName(packagePath)!);
        File.Copy(assetPath, packagePath);
        var provider = new DefaultFileProvider(contentRoot, SearchOption.AllDirectories, true, new VersionContainer(EGame.GAME_UE4_13));
        provider.Initialize();
        var key = provider.Files.Keys.Single(path => path.EndsWith("art/ui/" + exportName + ".uasset", StringComparison.OrdinalIgnoreCase));
        var package = provider.LoadPackage(key);
        if (package.ExportMapLength != 1) throw new InvalidDataException("CUE4Parse found an unexpected export count.");
        var export = package.ExportsLazy.Single().Value;
        if (!StringComparer.Ordinal.Equals(export.ExportType, "IggyPlayer"))
            throw new InvalidDataException("CUE4Parse did not identify the rebuilt export as IggyPlayer.");
        var propertyTags = (IEnumerable)export.GetType().GetProperty("Properties")!.GetValue(export)!;
        var textTag = propertyTags.Cast<object>().Single(tag => tag.GetType().GetField("Name")!.GetValue(tag)!.ToString() == "TextTable");
        var array = textTag.GetType().GetField("Tag")!.GetValue(textTag)!;
        var scriptArray = array.GetType().GetProperty("Value")!.GetValue(array)!;
        var rows = (ICollection)scriptArray.GetType().GetField("Properties")!.GetValue(scriptArray)!;
        if (rows.Count != expectedTextRows)
            throw new InvalidDataException($"CUE4Parse saw {rows.Count} TextTable rows; expected {expectedTextRows}.");
    }
    finally
    {
        try { Directory.Delete(Path.GetDirectoryName(contentRoot)!, recursive: true); }
        catch { /* Keep the validated output even if OS cleanup of the temporary parser copy fails. */ }
    }
}

sealed record TextRow(string Id, string Namespace, string Key, string Source);
