import SwiftUI
import AVKit

struct MediaPreviewView: View {
    let path: String
    @State private var player: AVPlayer?
    private var supported: Bool { ["mp4", "m4v", "mov"].contains(URL(fileURLWithPath: path).pathExtension.lowercased()) }
    var body: some View {
        if supported {
            VideoPlayer(player: player).frame(height: 220)
                .onAppear { if player == nil { player = AVPlayer(url: URL(fileURLWithPath: path)) } }
                .onDisappear { player?.pause() }
            Text("Preview playback does not record acceptance. Use the review controls after checking the content.").font(.caption).foregroundStyle(.secondary)
        } else { Text("An in-app preview is available for MP4 and QuickTime video. Encode a compatible candidate or open this original with your preferred player.").font(.caption).foregroundStyle(.secondary) }
    }
}
