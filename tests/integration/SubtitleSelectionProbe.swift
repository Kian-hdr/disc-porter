import Foundation
import AVFoundation

// AVFoundation delivers these callbacks on the explicitly supplied main queue.
final class CueReceiver: NSObject, AVPlayerItemLegibleOutputPushDelegate {
    var cues: [String] = []
    func legibleOutput(_ output: AVPlayerItemLegibleOutput, didOutputAttributedStrings strings: [NSAttributedString], nativeSampleBuffers: [Any], forItemTime itemTime: CMTime) {
        for value in strings where !value.string.isEmpty { cues.append(value.string) }
    }
}

@main struct SubtitleSelectionProbe {
    @MainActor static func main() async throws {
        let asset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
        let tracks = try await asset.loadTracks(withMediaType: .subtitle)
        guard let group = try await asset.loadMediaSelectionGroup(for: .legible),
              let option = group.options.first(where: { $0.locale?.language.languageCode?.identifier == "en" }) ?? group.options.first else {
            throw NSError(domain: "DiscPorterProbe", code: 1, userInfo: [NSLocalizedDescriptionKey: "No selectable subtitle option"])
        }
        let item = AVPlayerItem(asset: asset)
        let receiver = CueReceiver()
        let output = AVPlayerItemLegibleOutput()
        output.suppressesPlayerRendering = true
        output.setDelegate(receiver, queue: .main)
        item.add(output)
        item.select(option, in: group)
        let player = AVPlayer(playerItem: item)
        player.automaticallyWaitsToMinimizeStalling = false
        player.play()
        try await Task.sleep(for: .seconds(4))
        player.pause()
        let result: [String: Any] = ["subtitle_tracks": tracks.count,
            "options": group.options.count, "cues": receiver.cues,
            "selected": item.currentMediaSelection.selectedMediaOption(in: group)?.displayName ?? "",
            "ready": item.status == .readyToPlay, "error": item.error?.localizedDescription ?? ""]
        let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
}
