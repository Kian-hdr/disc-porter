import SwiftUI

struct ArchiveSettingsView: View {
    let store: ArchiveStore
    @State private var draft = ArchiveSettings()
    @State private var loaded = false
    @State private var saved = false

    var body: some View {
        Form {
            Section("Archive folder") {
                Text(draft.outputRoot.isEmpty ? "Choose a folder on your archive drive" : draft.outputRoot)
                    .foregroundStyle(.secondary).textSelection(.enabled)
                Button("Choose folder…") {
                    if let path = FilePanels.folder() { draft.outputRoot = path; saved = false }
                }
                Text("Changing this folder affects new jobs. Existing jobs keep their recorded destination.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Automatic starts") {
                Toggle("Start known discs when inserted", isOn: $draft.autoStart)
                Text("Only an exact saved disc profile starts automatically. New discs need their titles and destination confirmed once. Prepare to disconnect turns this off.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Encoding") {
                Picker("Video", selection: $draft.videoCodec) {
                    Text("HEVC / H.265").tag("hevc")
                    Text("H.264 compatibility").tag("h264")
                }
                Stepper("Quality: CRF \(draft.quality)", value: $draft.quality, in: 14...30)
                Text("Lower CRF values favor quality and larger files. The engine preserves supported source resolution and bit depth; unsupported sources pause for review.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Audio and originals") {
                Text("English and German primary audio tracks are retained when present.")
                Text("Complete originals, including subtitles and alternate mixes, stay in the archive. No automatic deletion is enabled.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            HStack {
                Text(saved ? "Settings saved" : "").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Save settings") {
                    Task { await store.settings(draft); saved = store.status?.settings == draft }
                }.buttonStyle(.borderedProminent).disabled(!store.connected || store.busy || draft.outputRoot.isEmpty)
            }
        }
        .formStyle(.grouped)
        .frame(width: 570, height: 670)
        .onAppear {
            if !loaded, let settings = store.status?.settings { draft = settings; loaded = true }
        }
        .onChange(of: store.status?.settings) { _, settings in
            if !loaded, let settings { draft = settings; loaded = true }
        }
    }
}
