import Foundation
import Testing
@testable import DiscArchive

struct APICompatibilityTests {
    @Test func backendStatusAndProgressDecode() throws {
        let json = #"""
        {"settings":{"output_root":"/synthetic/archive","auto_start":false,"video_codec":"hevc","quality":18,"languages":["eng","deu"],"_identity":{}},
         "jobs":[{"id":"abc","collection":"Synthetic","kind":"film","state":"running","phase":"encode","checkpoint":"acquire","stop_after":"complete","source_path":"/synthetic/source.mkv","output_path":"/synthetic/archive/Synthetic","progress":0.4,"message":"Encoding","safe_to_disconnect":false,"titles":[{"id":0,"name":"Film"}],"created_at":"2026-10-02T00:00:00Z","updated_at":"2026-10-02T00:00:01Z","phase_progress":0.3,"processed_bytes":1000000,"pause_requested":true,"current_title":"Film","last_progress_at":"2026-10-02T00:00:01Z","heartbeat_at":"2026-10-02T00:00:02Z","next_checkpoint":"encode"}],
         "discs":[],"tools":{"makemkv":null,"ffmpeg":"/synthetic/ffmpeg","ffprobe":"/synthetic/ffprobe"},"safe_to_disconnect":false,"message":"Running"}
        """#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value = try decoder.decode(EngineStatus.self, from: Data(json.utf8))
        #expect(value.jobs[0].phaseProgress == 0.3)
        #expect(value.jobs[0].pauseRequested == true)
        #expect(value.jobs[0].totalBytes == nil)
        #expect(value.jobs[0].processedBytes == 1_000_000)
        #expect(!value.safeToDisconnect)
    }

    @Test func knownProfileSubsetAndKindDecode() throws {
        let json = #"""
        {"discs":[{"id":"synthetic-fingerprint","label":"Synthetic disc","format":"DVD","source_path":"/synthetic/disc","drive_index":2,"identified":true,"collection":"Synthetic Show","kind":"series","titles":[{"id":1,"name":"Unidentified title 1","duration":"00:01:00","size":"1 MB","selected":false},{"id":4,"name":"S01E01_Chosen_Episode","duration":"00:20:00","size":"20 MB","selected":true}],"message":"Saved mapping"}]}
        """#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value = try decoder.decode(ScanReply.self, from: Data(json.utf8))
        #expect(value.discs[0].kind == "series")
        let selected = value.discs[0].titles.filter { $0.selected == true }
        #expect(selected.map(\.id) == [4])
        #expect(selected[0].name == "S01E01_Chosen_Episode")
    }
}
