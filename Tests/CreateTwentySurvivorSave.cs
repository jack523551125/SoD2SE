// Offline fixture builder. Uses the user's Community Editor SaveParser assembly.
// It writes ONLY to a new output directory; never overwrites active saves.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using SaveParser;

class CreateTwentySurvivorSave
{
    static int DuplicateItem(StructObject library, int index)
    {
        if (index < 0) return index;
        var order = library.GetSub("ItemOrder");
        string kind = order.TheStats[index].Value;
        string type = kind.Substring("EItemTypeIndex::".Length);
        int position = order.TheStats.Take(index).Count(x => x.Value == kind);
        var list = library.GetSub(type + "ItemInstances");
        StructObject clone;
        list.TheSubs[position].CloneInto(list, out clone, true);
        var entry = new ByteProperty(order, "ItemOrder", kind, "");
        var ammo = clone.GetSub("AmmoItemInstance");
        if (ammo != null)
            ammo.SetValue<int>("Index", DuplicateItem(library, ammo.GetValue<int>("Index")));
        return entry.Index;
    }

    static IEnumerable<StructObject> Walk(StructObject item)
    {
        yield return item;
        foreach (var child in item.TheSubs)
            foreach (var nested in Walk(child)) yield return nested;
    }

    static byte[] Rebuild(StructObject item)
    {
        var bytes = new List<byte>();
        typeof(StructObject).GetMethod("RebuildCore", BindingFlags.Instance | BindingFlags.NonPublic)
            .Invoke(item, new object[] { bytes });
        return bytes.ToArray();
    }

    static void Unchanged(StructObject before, StructObject after)
    {
        if (before.TheStats.Count != after.TheStats.Count || before.TheSubs.Count != after.TheSubs.Count)
            throw new Exception("Unexpected layout change: " + before.PropertyName);
        for (int i = 0; i < before.TheStats.Count; i++)
        {
            var a = before.TheStats[i]; var b = after.TheStats[i];
            if (a.PropertyName != b.PropertyName || a.Value != b.Value)
                throw new Exception("Unexpected value change: " + a.PropertyName);
        }
        for (int i = 0; i < before.TheSubs.Count; i++)
        {
            var a = before.TheSubs[i]; var b = after.TheSubs[i];
            if (a.PropertyName != b.PropertyName) throw new Exception("Subtree identity changed.");
            if (a.PropertyName == "SurvivorSaves" || a.PropertyName == "ItemLibrary") continue;
            if (a.PropertyName == "CommunitySave" || a.PropertyName == "Enclave") Unchanged(a, b);
            else if (!Rebuild(a).SequenceEqual(Rebuild(b))) throw new Exception("Unexpected subtree change: " + a.PropertyName);
        }
    }

    static int Main(string[] args)
    {
        try
        {
            if (args.Length != 3) throw new Exception("Usage: <community.sav> <SaveUser.sav> <new-output-directory>");
            if (Directory.Exists(args[2])) throw new Exception("Output directory must not exist.");
            var game = new StructRoot(args[0]); var user = new StructRoot(args[1]);
            var core = game.GetSub(0); var account = user.GetSub(0);
            var community = core.GetSub("CommunitySave");
            var survivors = community.GetSub("Enclave").GetSub("SurvivorSaves");
            var donors = survivors.TheSubs.ToArray();
            if (donors.Length == 0 || donors.Length >= 20) throw new Exception("Expected 1..19 original members.");
            if (donors.Any(x => x.GetValue<int>("bIsDead") != 0 || x.GetValue<int>("bIsDeparted") != 0))
                throw new Exception("Unexpected dead/departed community members.");
            var originals = donors.Select(Rebuild).ToArray();
            var allIds = Walk(game).Concat(Walk(user))
                .Where(x => x.PropertyType == "SurvivorSave" && x.TheStats.Any(s => s.PropertyName == "ID"))
                .Select(x => x.GetValue<int>("ID")).ToArray();
            int nextId = Math.Max(account.GetValue<int>("NextAvailableSurvivorID"), checked(allIds.Max() + 1));
            int firstId = nextId;
            while (survivors.TheSubs.Count < 20)
            {
                int number = survivors.TheSubs.Count + 1;
                StructObject clone;
                donors[(number - donors.Length - 1) % donors.Length].CloneInto(survivors, out clone, true);
                clone.SetValue<int>("ID", nextId); nextId = checked(nextId + 1);
                clone.GetSub("NickName").SetTextValue("TEST " + number.ToString("00"));
                clone.GetSub("FamilyRelationships").Wipe();
                var narrative = clone.GetSub("NarrativeEntityId");
                narrative.SetValue<string>("NarrativeId", "None");
                narrative.SetValue<string>("EntityId", "None");
                clone.SetValue<float>("FatigueCounter", 0);
                var slots = clone.GetSub("Equipment").TheSubs.Concat(clone.GetSub("Inventory").GetSub("Slots").TheSubs);
                foreach (var slot in slots)
                    slot.SetValue<int>("Index", DuplicateItem(community.GetSub("ItemLibrary"), slot.GetValue<int>("Index")));
            }
            account.SetValue<int>("NextAvailableSurvivorID", nextId);
            for (int i = 0; i < donors.Length; i++)
                if (!originals[i].SequenceEqual(Rebuild(donors[i]))) throw new Exception("Original member changed.");
            Directory.CreateDirectory(args[2]);
            game.Save(Path.Combine(args[2], Path.GetFileName(args[0])));
            user.Save(Path.Combine(args[2], "SaveUser.sav"));
            var check = new StructRoot(Path.Combine(args[2], Path.GetFileName(args[0])));
            var members = check.GetSub(0).GetSub("CommunitySave").GetSub("Enclave").GetSub("SurvivorSaves").TheSubs;
            if (members.Count != 20 || members.Select(x => x.GetValue<int>("ID")).Distinct().Count() != 20)
                throw new Exception("Roundtrip membership validation failed.");
            var checkUser = new StructRoot(Path.Combine(args[2], "SaveUser.sav"));
            if (checkUser.GetSub(0).GetValue<int>("NextAvailableSurvivorID") != nextId)
                throw new Exception("Account ID allocator roundtrip failed.");
            var pristine = new StructRoot(args[0]);
            Unchanged(pristine.GetSub(0), check.GetSub(0));
            for (int i = 0; i < donors.Length; i++)
                if (!originals[i].SequenceEqual(Rebuild(members[i]))) throw new Exception("Original member roundtrip changed.");
            var originalAccount = new StructRoot(args[1]).GetSub(0);
            checkUser.GetSub(0).SetValue<int>("NextAvailableSurvivorID", originalAccount.GetValue<int>("NextAvailableSurvivorID"));
            if (!Rebuild(originalAccount).SequenceEqual(Rebuild(checkUser.GetSub(0))))
                throw new Exception("Account changed outside ID allocator.");
            var library = check.GetSub(0).GetSub("CommunitySave").GetSub("ItemLibrary");
            int itemCount = library.GetSub("ItemOrder").TheStats.Count;
            foreach (var group in library.GetSub("ItemOrder").TheStats.GroupBy(x => x.Value))
                if (library.GetSub(group.Key.Substring("EItemTypeIndex::".Length) + "ItemInstances").TheSubs.Count != group.Count())
                    throw new Exception("Item library order/type count mismatch.");
            var occupied = new HashSet<int>();
            foreach (var member in members)
                foreach (var slot in member.GetSub("Equipment").TheSubs.Concat(member.GetSub("Inventory").GetSub("Slots").TheSubs))
                {
                    int index = slot.GetValue<int>("Index");
                    if (index < 0) continue;
                    if (index >= itemCount || !occupied.Add(index)) throw new Exception("Invalid/shared survivor item reference.");
                }
            File.WriteAllText(Path.Combine(args[2], "verification.txt"),
                "Members: 20\r\nOriginal members preserved: " + donors.Length +
                "\r\nNew survivor IDs: " + firstId + ".." + (nextId - 1) +
                "\r\nEquipment and inventory instances duplicated independently; references validated.\r\nNon-target subtrees and original members preserved after roundtrip.\r\nAccount changed only in next survivor ID allocator.\r\nSaveParser roundtrip passed; not game-tested.\r\n");
            Console.WriteLine(File.ReadAllText(Path.Combine(args[2], "verification.txt")));
            return 0;
        }
        catch (Exception e) { Console.Error.WriteLine(e); return 1; }
    }
}
