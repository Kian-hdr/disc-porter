import SwiftUI

struct JobPlanEditor: View {
    let store: ArchiveStore
    let job: ArchiveJob
    @State private var draft = ArchiveSettings()
    @State private var base = ArchiveSettings()
    @State private var titles: [TitleDraft] = []
    @State private var category = "video"
    @State private var preview: JSONValue = .null
    @State private var previewBody: [String: JSONValue] = [:]
    @State private var loadedRevision = 0
    @State private var confirmTransforms = false
    private var bodyRequest: [String: JSONValue] {
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let selected = titles.filter(\.selected).map(\.title)
        let data = try? encoder.encode(selected)
        let value = data.flatMap { try? JSONDecoder().decode(JSONValue.self, from: $0) } ?? .array([])
        return ["expected_revision": .number(Double(loadedRevision)), "overrides": .object(draft.changes(from: base)), "titles": value, "confirm_transforms": .bool(confirmTransforms)]
    }
    var body: some View {
        GroupBox("Edit future processing") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Changes apply only at a checkpoint. Existing generations remain available; the preview explains which phases restart.").font(.caption).foregroundStyle(.secondary)
                Picker("Recipe section", selection: $category) {
                    ForEach(RecipeCategory.all.filter { ["video", "audio", "subtitles", "retention"].contains($0.id) }) { Text($0.title).tag($0.id) }
                }
                Form { RecipeEditor(draft: $draft, schema: store.schema, fields: RecipeCategory.all.first { $0.id == category }?.fields) }.formStyle(.grouped).frame(minHeight: 300)
                ForEach($titles) { $title in TitleSelectionView(title: $title, kind: job.kind, schema: store.schema, fallback: draft) }
                if let changes = job.pendingChanges, changes != .array([]) { StructuredValueView(value: changes) }
                if preview != .null { StructuredValueView(value: preview) }
                if preview["requires_confirmation"].bool || job.pendingChanges?.array.isEmpty == false { Toggle("Approve the listed source transformations", isOn: $confirmTransforms) }
                if loadedRevision != job.revision { Text("This job changed elsewhere. Reload the plan to continue.").font(.caption).foregroundStyle(.orange) }
                HStack {
                    Button("Reload") { load() }
                    Button("Preview changes") { Task { let request = bodyRequest; preview = await store.query("POST", "/jobs/\(job.id)/plan-preview", request) ?? .null; previewBody = request } }.disabled(loadedRevision != job.revision || store.busy || !titles.filter(\.selected).allSatisfy(\.metadataValid))
                    Spacer()
                    Button("Apply plan") { Task { await store.mutate("PATCH", "/jobs/\(job.id)", previewBody); if store.error == nil { preview = .null } } }
                        .buttonStyle(.borderedProminent).disabled(!preview["can_apply"].bool || previewBody != bodyRequest || loadedRevision != job.revision || store.busy)
                }
            }.padding(10)
        }.onAppear { load() }
    }
    private func load() {
        confirmTransforms = false; base = job.settings ?? ArchiveSettings(); draft = base; loadedRevision = job.revision ?? 0; preview = .null
        titles = job.titles.map { title in
            var result = TitleDraft(id: title.id, selected: true, name: title.name)
            result.season = title.season.map(String.init) ?? ""; result.episode = title.episode.map(String.init) ?? ""; result.year = title.year.map(String.init) ?? ""
            result.audioIDs = Set(title.audioStreams ?? []); result.subtitleIDs = Set(title.subtitleStreams ?? [])
            result.manualAudio = title.audioStreams != nil; result.manualSubtitles = title.subtitleStreams != nil
            result.overrides = title.overrides
            result.defaultAudioID = title.defaultAudioStream; result.defaultSubtitleID = title.defaultSubtitleStream
            result.overrideForced = title.forcedSubtitleStreams != nil; result.forcedIDs = Set(title.forcedSubtitleStreams ?? [])
            if let artifact = job.artifacts?.first(where: { Int($0["title_id"].number ?? -1) == title.id }) {
                result.streams = artifact["source_probe"]["streams"].array
            } else if let raw = job.discStreams?[String(title.id)] {
                result.streams = raw.object.keys.sorted().map { key in var stream = raw[key]; stream["index"] = .number(Double(key) ?? 0); return stream }
            }
            return result
        }
    }
}
