import SwiftUI

struct RecipeCategory: Identifiable {
    let id: String
    let title: String
    let fields: [String]
    static let all: [Self] = [
        .init(id: "destination", title: "Folders & storage", fields: ["output_root", "work_root", "original_root", "folder_layout", "file_template", "reserve_bytes"]),
        .init(id: "video", title: "Video", fields: ["mode", "output_container", "video_codec", "encoder", "speed", "quality", "bitrate_kbps", "bit_depth", "resolution", "frame_rate", "deinterlace", "aspect"]),
        .init(id: "audio", title: "Audio", fields: ["languages", "audio_policy", "audio_codec", "audio_bitrate_kbps", "audio_channels", "include_commentary", "default_audio_language", "preserve_original_audio"]),
        .init(id: "subtitles", title: "Subtitles", fields: ["subtitle_policy", "subtitle_languages", "default_subtitle_language", "preserve_bitmap_subtitles"]),
        .init(id: "automation", title: "Automation & resources", fields: ["auto_start", "default_checkpoint", "on_battery", "auto_resume", "retry_count", "max_encoders", "cpu_threads", "notifications"]),
        .init(id: "retention", title: "Original retention", fields: ["cleanup_policy"]),
        .init(id: "appearance", title: "Appearance", fields: ["appearance"]),
        .init(id: "tools", title: "Processing tools", fields: ["ffmpeg_path", "ffprobe_path", "makemkv_path"])
    ]
    static let recipeKeys = Set(all.filter { !["appearance", "tools", "automation"].contains($0.id) }.flatMap(\.fields))
}

struct RecipeEditor: View {
    @Binding var draft: ArchiveSettings
    let schema: [String: JSONValue]
    var fields: [String]? = nil
    var search = ""
    var fallback = ArchiveSettings()
    var body: some View {
        ForEach((fields ?? schema.keys.sorted()).filter { key in schema[key] != nil && !["schema_version", "revision", "preset_id"].contains(key) && (search.isEmpty || fieldLabel(key).localizedCaseInsensitiveContains(search)) }, id: \.self) { key in
            RecipeField(key: key, definition: schema[key] ?? .null, draft: $draft, fallback: fallback)
        }
    }
}

struct RecipeField: View {
    let key: String
    let definition: JSONValue
    @Binding var draft: ArchiveSettings
    var fallback = ArchiveSettings()
    private var value: JSONValue { draft.values[key] ?? fallback.values[key] ?? definition["default"] }
    private var choices: [JSONValue] { definition["enum"].array }
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let minimum = definition["minimum"].number, minimum == definition["maximum"].number {
                LabeledContent(fieldLabel(key), value: String(Int(minimum)))
            } else if key == "reserve_bytes" {
                HStack {
                    Text("Keep free space (GB)"); Spacer()
                    TextField("Gigabytes", value: Binding(get: { (value.number ?? 0) / 1_000_000_000 }, set: { draft[key] = .number(($0 * 1_000_000_000).rounded()) }), format: .number)
                        .multilineTextAlignment(.trailing).frame(maxWidth: 140)
                }
            } else if !choices.isEmpty {
                Picker(fieldLabel(key), selection: Binding(get: { value.string }, set: { draft[key] = .string($0) })) {
                    ForEach(choices.map(\.string), id: \.self) { Text(choiceLabel($0)).tag($0) }
                }
            } else if ["boolean", "bool"].contains(definition["type"].string) {
                Toggle(fieldLabel(key), isOn: Binding(get: { value.bool }, set: { draft[key] = .bool($0) }))
            } else if ["integer", "number", "int"].contains(definition["type"].string) {
                HStack {
                    Text(fieldLabel(key)); Spacer()
                    TextField("Value", value: Binding(get: { value.number ?? 0 }, set: { draft[key] = .number($0) }), format: .number)
                        .multilineTextAlignment(.trailing).frame(maxWidth: 140)
                }
                if let minimum = definition["minimum"].number, let maximum = definition["maximum"].number {
                    Text("Supported range: \(Int(minimum))–\(Int(maximum))").font(.caption).foregroundStyle(.secondary)
                }
            } else if definition["type"].string == "array" {
                TextField(fieldLabel(key), text: Binding(get: { value.array.map(\.display).joined(separator: ", ") }, set: { draft[key] = .strings($0.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }) }))
                Text("Comma-separated language codes; empty includes all languages.").font(.caption).foregroundStyle(.secondary)
            } else {
                HStack {
                    TextField(fieldLabel(key), text: Binding(get: { value.string }, set: { draft[key] = .string($0) }))
                    if key.hasSuffix("_root") {
                        Button("Choose…") { Task { if let path = await FilePanels.folder(title: fieldLabel(key)) { draft[key] = .string(path) } } }
                    }
                }
            }
            if let hint = fieldHint(key) { Text(hint).font(.caption).foregroundStyle(.secondary) }
        }
    }
}

func fieldLabel(_ key: String) -> String {
    let labels = ["quality": "Quality (CRF)", "bitrate_kbps": "Target video bitrate (kbps)", "audio_bitrate_kbps": "Audio bitrate (kbps)", "reserve_bytes": "Keep free space (bytes)", "cpu_threads": "CPU threads (0 = automatic)", "max_encoders": "Concurrent encoders", "ffmpeg_path": "FFmpeg override", "ffprobe_path": "FFprobe override", "makemkv_path": "MakeMKV override"]
    return labels[key] ?? key.replacingOccurrences(of: "_", with: " ").capitalized
}
func choiceLabel(_ value: String) -> String {
    ["keep": "Keep originals", "delete_verified": "Permanently delete verified temporary originals", "source": "Preserve source", "system": "Follow macOS", "original": "Original archive", "transcode": "Transcode", "copy": "Preserve tracks", "main_per_language": "Main track per language" ][value] ?? value.replacingOccurrences(of: "_", with: " ").capitalized
}
func fieldHint(_ key: String) -> String? {
    switch key {
    case "cleanup_policy": "Keep is the default. Permanent deletion is irreversible and applies only to app-created temporary originals after technical verification and stream preservation. Playback remains unproven; imported sources remain."
    case "mode": "Original archive preserves source features. HDR and Dolby Vision require original mode."
    case "quality": "Lower CRF increases quality and file size. Hardware encoding uses an explicit target bitrate."
    case "file_template": "Use {title}. Existing output files are never overwritten."
    case "work_root": "Empty uses the archive folder. Changing folders affects new jobs."
    case "cpu_threads": "0 selects automatic resource use."
    case "appearance": "Changes app content appearance. macOS manages the app icon independently."
    default: nil
    }
}
