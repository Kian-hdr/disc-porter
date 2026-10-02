import SwiftUI

struct ProfilesView: View {
    let store: ArchiveStore
    @State private var selection: String?
    var body: some View {
        HSplitView {
            List(selection: $selection) {
                Section("Encoding presets") {
                    ForEach(store.presets, id: \.stableID) { value in
                        Label(value["name"].string, systemImage: value["builtin"].bool ? "lock" : "slider.horizontal.3").tag("preset:" + value["id"].string)
                    }
                }
                Section("Saved discs") {
                    ForEach(store.profiles, id: \.stableID) { value in Text(value["collection"].string).tag("disc:" + value["disc_id"].string) }
                }
            }.frame(minWidth: 180, idealWidth: 225, maxWidth: 280)
            if let preset = store.presets.first(where: { "preset:" + $0["id"].string == selection }) {
                PresetDetailView(store: store, preset: preset).id(preset["id"].string)
            } else if let profile = store.profiles.first(where: { "disc:" + $0["disc_id"].string == selection }) {
                DiscProfileDetailView(store: store, profile: profile).id(profile["disc_id"].string)
            } else { ContentUnavailableView("Presets & saved discs", systemImage: "slider.horizontal.3", description: Text("Choose a preset to duplicate or edit, or manage a confirmed disc mapping.")) }
        }
    }
}

struct PresetDetailView: View {
    let store: ArchiveStore
    let preset: JSONValue
    @State private var draft = ArchiveSettings()
    @State private var name = ""
    @State private var duplicateName = ""
    @State private var category = "video"
    @State private var confirmDelete = false
    @State private var loadedRevision: JSONValue = .null
    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("Preset") {
                    TextField("Name", text: $name).disabled(preset["builtin"].bool)
                    if loadedRevision != preset["revision"] {
                        Text("This preset changed elsewhere. Reload before saving.").font(.caption).foregroundStyle(.orange)
                        Button("Reload preset") { loadedRevision = preset["revision"]; draft = ArchiveSettings(values: preset["settings"].object); name = preset["name"].string }
                    }
                    if preset["builtin"].bool { Text("Built-in presets are preserved. Duplicate to customize.").font(.caption).foregroundStyle(.secondary) }
                    Picker("Recipe section", selection: $category) {
                        ForEach(RecipeCategory.all.filter { ["video", "audio", "subtitles", "destination", "retention"].contains($0.id) }) { Text($0.title).tag($0.id) }
                    }
                }
                Section {
                    RecipeEditor(draft: $draft, schema: store.schema, fields: (RecipeCategory.all.first { $0.id == category }?.fields ?? []).filter { preset["settings"].object[$0] != nil })
                }.disabled(preset["builtin"].bool)
                Section("Duplicate preset") {
                    TextField("New preset name", text: $duplicateName)
                    Button("Create duplicate") { Task { await store.mutate("POST", "/presets", ["name": .string(duplicateName), "base_id": preset["id"]]); duplicateName = "" } }.disabled(duplicateName.trimmingCharacters(in: .whitespaces).isEmpty || store.busy)
                }
            }.formStyle(.grouped)
            if !preset["builtin"].bool {
                HStack {
                    Button("Delete preset", role: .destructive) { confirmDelete = true }
                    Spacer()
                    Button("Save preset") { Task { await store.mutate("PATCH", "/presets/\(preset["id"].string)", ["expected_revision": loadedRevision, "name": .string(name), "settings": .object(draft.values)]) } }.buttonStyle(.borderedProminent).disabled(loadedRevision != preset["revision"])
                }.padding().disabled(store.busy)
            }
        }.onAppear { loadedRevision = preset["revision"]; draft = ArchiveSettings(values: preset["settings"].object); name = preset["name"].string; duplicateName = name + " copy" }
        .confirmationDialog("Delete this custom preset?", isPresented: $confirmDelete) {
            Button("Delete preset", role: .destructive) { Task { await store.mutate("DELETE", "/presets/\(preset["id"].string)", ["expected_revision": loadedRevision]) } }
        } message: { Text("Existing job recipes remain unchanged.") }
    }
}

struct DiscProfileDetailView: View {
    let store: ArchiveStore
    let profile: JSONValue
    @State private var collection = ""
    @State private var kind = "film"
    @State private var titles: [ArchiveTitle] = []
    @State private var overrides = ArchiveSettings()
    @State private var category = "video"
    @State private var confirmDelete = false
    @State private var loadedRevision: JSONValue = .null
    var body: some View {
        Form {
            Section("Confirmed disc mapping") {
                TextField("Collection", text: $collection)
                if loadedRevision != profile["revision"] {
                    Text("This mapping changed elsewhere. Reload before saving.").font(.caption).foregroundStyle(.orange)
                    Button("Reload mapping") {
                        loadedRevision = profile["revision"]; collection = profile["collection"].string; kind = profile["kind"].string
                        overrides = ArchiveSettings(values: profile["overrides"].object)
                        titles = decodeTitles(profile["titles"])
                    }
                }
                Picker("Kind", selection: $kind) { Text("Film").tag("film"); Text("Series").tag("series"); Text("Extras").tag("extras") }
                ForEach($titles) { $title in TextField("Title \(title.id)", text: $title.name) }
                Text(profile["disc_id"].string).font(.caption.monospaced()).textSelection(.enabled)
            }
            Section("Disc recipe overrides") {
                Picker("Section", selection: $category) {
                    ForEach(RecipeCategory.all.filter { ["video", "audio", "subtitles", "retention"].contains($0.id) }) { Text($0.title).tag($0.id) }
                }
                RecipeEditor(draft: $overrides, schema: store.schema, fields: RecipeCategory.all.first { $0.id == category }?.fields, fallback: store.status?.settings ?? ArchiveSettings())
                Text("Only controls you change become disc-specific overrides. Existing jobs keep their snapshots.").font(.caption).foregroundStyle(.secondary)
            }
            Section {
                HStack {
                    Button("Forget disc", role: .destructive) { confirmDelete = true }
                    Spacer()
                    Button("Save mapping") { Task {
                        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
                        let encoded = try? encoder.encode(titles)
                        let value = encoded.flatMap { try? JSONDecoder().decode(JSONValue.self, from: $0) } ?? .array([])
                        await store.mutate("PATCH", "/profiles/\(profile["disc_id"].string)", ["expected_revision": loadedRevision, "collection": .string(collection), "kind": .string(kind), "titles": value, "overrides": .object(overrides.values)])
                    } }.buttonStyle(.borderedProminent).disabled(loadedRevision != profile["revision"])
                }.disabled(store.busy)
            }
        }.formStyle(.grouped).onAppear {
            loadedRevision = profile["revision"]; overrides = ArchiveSettings(values: profile["overrides"].object); collection = profile["collection"].string; kind = profile["kind"].string
            titles = decodeTitles(profile["titles"])
        }.confirmationDialog("Forget this disc mapping?", isPresented: $confirmDelete) {
            Button("Forget mapping", role: .destructive) { Task { await store.mutate("DELETE", "/profiles/\(profile["disc_id"].string)", ["expected_revision": loadedRevision]) } }
        } message: { Text("Files and existing jobs remain. This disc will need confirmation before automatic processing.") }
    }
}
