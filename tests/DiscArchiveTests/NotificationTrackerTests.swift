import Foundation
import Testing
@testable import DiscArchive

struct NotificationTrackerTests {
    private func job(_ state: String, generation: Int = 1) throws -> ArchiveJob {
        let raw: [String: JSONValue] = [
            "id": .string("synthetic-job"), "collection": .string("Synthetic"), "kind": .string("film"),
            "state": .string(state), "generation": .number(Double(generation)), "phase": .string("complete"),
            "checkpoint": .string("verify"), "stop_after": .string("complete"),
            "source_path": .string("/synthetic/private-source"), "output_path": .string("/synthetic/archive"),
            "progress": .number(1), "message": .string("Synthetic detail with /synthetic/private-source"),
            "safe_to_disconnect": .bool(true), "titles": .array([.object(["id": .number(0), "name": .string("Film")])]),
            "created_at": .string("2026-10-02T00:00:00Z"), "updated_at": .string("2026-10-02T00:00:01Z")
        ]
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ArchiveJob.self, from: JSONEncoder().encode(raw))
    }
    @Test func historicalSnapshotDoesNotNotifyAndCompletionDeduplicates() throws {
        var tracker = NotificationTracker()
        #expect(tracker.changes([try job("completed")]).isEmpty)
        #expect(tracker.changes([try job("running")]).isEmpty)
        let changes = tracker.changes([try job("completed")])
        #expect(changes.count == 1)
        #expect(changes[0].completed)
        #expect(changes[0].jobID == "synthetic-job")
        #expect(!changes[0].identifier.contains("private-source"))
        #expect(tracker.changes([try job("completed")]).isEmpty)
    }
    @Test func errorsAndNewGenerationsHaveDistinctOpaqueNoticeKeys() throws {
        var tracker = NotificationTracker()
        _ = tracker.changes([try job("running")])
        let failed = tracker.changes([try job("failed")])
        #expect(failed.count == 1 && !failed[0].completed)
        #expect(tracker.changes([try job("failed")]).isEmpty)
        _ = tracker.changes([try job("running", generation: 2)])
        let complete = tracker.changes([try job("completed", generation: 2)])
        #expect(complete.count == 1)
        #expect(complete[0].identifier != failed[0].identifier)
    }
    @Test func freshStatusCarriesPresetsBeforeNavigation() throws {
        let raw = #"{"settings":{"revision":1,"preset_id":"balanced"},"jobs":[],"discs":[],"tools":{},"safe_to_disconnect":true,"message":"Ready","api_version":2,"engine_version":"0.2.0","presets":[{"id":"balanced","name":"Balanced","builtin":true,"revision":1,"settings":{"quality":20}}]}"#
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let status = try decoder.decode(EngineStatus.self, from: Data(raw.utf8))
        #expect(status.presets?.count == 1)
        #expect(status.presets?[0]["id"].string == "balanced")
    }
}
