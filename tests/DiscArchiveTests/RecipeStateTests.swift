import Foundation
import Testing
@testable import DiscArchive

struct RecipeStateTests {
    @Test func dynamicSettingsPreserveV2AndUnknownAdditions() throws {
        let raw = #"{"schema_version":2,"revision":7,"output_root":"/synthetic/archive","appearance":"dark","audio_policy":"all","languages":[],"future_option":{"enabled":true},"_identity":{"volume_uuid":"synthetic"}}"#
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        var settings = try decoder.decode(ArchiveSettings.self, from: Data(raw.utf8))
        #expect(settings.revision == 7)
        #expect(settings.appearance == "dark")
        #expect(settings["future_option"]["enabled"].bool)
        let base = settings
        settings.quality = 22
        settings["appearance"] = .string("system")
        let patch = settings.changes(from: base)
        #expect(Set(patch.keys) == ["quality", "appearance"])
        #expect(patch["quality"] == .number(22))
        #expect(patch["_identity"] == nil)
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let roundtrip = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(settings))
        #expect(roundtrip["audio_policy"].string == "all")
        #expect(roundtrip["future_option"]["enabled"].bool)
    }

    @Test func titleRequestPreservesExplicitSelectionAndDoesNotInventMetadata() throws {
        var title = TitleDraft(id: 4, selected: true, name: "S01E02_Synthetic")
        title.season = "1"; title.episode = "2"; title.manualAudio = true; title.audioIDs = [3, 1]
        let value = title.title
        #expect(value.audioStreams == [1, 3])
        #expect(value.subtitleStreams == nil)
        #expect(value.year == nil)
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let encoded = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(value))
        #expect(encoded["audio_streams"].array == [.number(1), .number(3)])
        #expect(encoded["season"].number == 1)
        #expect(encoded["year"] == .null)
    }

    @Test func presetDraftsDoNotModifyBuiltinsOrLeakRuntimeFields() {
        let builtin = ArchiveSettings(values: ["quality": .number(20), "mode": .string("transcode")])
        var draft = builtin
        draft.quality = 25
        #expect(builtin.quality == 20)
        #expect(draft.changes(from: builtin) == ["quality": .number(25)])
        #expect(draft.values["_identity"] == nil)
    }

    @Test func recordIDsRemainStableWhenProgressOrNameChanges() {
        var record: JSONValue = .object(["id": .string("synthetic-job"), "name": .string("Old"), "progress": .number(0)])
        let id = record.stableID
        record["name"] = .string("New"); record["progress"] = .number(0.8)
        #expect(record.stableID == id)
    }
}

struct V2RequestTests {
    @Test func profileEditPreservesTitleOverridesAndSelections() throws {
        let raw: JSONValue = .array([.object(["id": .number(2), "name": .string("Synthetic episode"), "season": .number(1), "episode": .number(3), "audio_streams": .array([.number(1)]), "overrides": .object(["quality": .number(23)])])])
        var titles = decodeTitles(raw)
        #expect(titles.count == 1)
        titles[0].name = "Renamed synthetic episode"
        #expect(titles[0].audioStreams == [1])
        #expect(titles[0].overrides?.quality == 23)
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let value = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(titles))
        #expect(value.array[0]["audio_streams"].array == [.number(1)])
        #expect(value.array[0]["episode"].number == 3)
    }

    @Test func startRequestIncludesConfirmationAndRevision() throws {
        var request = JobRequest(sourcePath: "/synthetic/source.mkv", discId: nil, collection: "Synthetic", kind: "film", titles: [.init(id: 0, name: "Film")], stopAfter: "scan")
        request.expectedSettingsRevision = 5; request.confirmTransforms = true; request.rememberProfile = false
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let value = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(request))
        #expect(value["expected_settings_revision"].number == 5)
        #expect(value["confirm_transforms"].bool)
        #expect(value["remember_profile"] == .bool(false))
        #expect(value["disc_id"] == .null)
    }
}

struct StreamDispositionTests {
    @Test func explicitDefaultsForcedFlagsAndManualAudioRoundTrip() throws {
        var draft = TitleDraft(id: 0, selected: true, name: "Synthetic")
        draft.manualAudio = true; draft.audioIDs = [2]; draft.defaultAudioID = 2
        draft.manualSubtitles = true; draft.subtitleIDs = [4]; draft.defaultSubtitleID = 4
        draft.overrideForced = true; draft.forcedIDs = []
        let title = draft.title
        #expect(title.overrides?["audio_policy"].string == "selected")
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let raw = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(title))
        #expect(raw["default_audio_stream"].number == 2)
        #expect(raw["default_subtitle_stream"].number == 4)
        #expect(raw["forced_subtitle_streams"] == .array([]))
        #expect(decodeTitles(.array([raw]))[0].forcedSubtitleStreams == [])
        draft.overrideForced = false
        #expect(draft.title.forcedSubtitleStreams == nil)
    }
}

struct StartAttemptTests {
    @Test func retryReusesKeyUntilPlanChangesOrSucceeds() {
        var attempt = StartAttempt()
        let first = attempt.key(for: "synthetic-accepted-plan-1")
        #expect(attempt.key(for: "synthetic-accepted-plan-1") == first)
        let changed = attempt.key(for: "synthetic-accepted-plan-2")
        #expect(changed != first)
        #expect(attempt.key(for: "synthetic-accepted-plan-2") == changed)
        attempt.completed()
        #expect(attempt.idempotencyKey == nil)
        #expect(attempt.key(for: "synthetic-accepted-plan-2") != changed)
    }
    @Test func startEncodesAcceptedServerFingerprint() throws {
        var request = JobRequest(sourcePath: "/synthetic/source", discId: nil, collection: "Synthetic", kind: "film", titles: [.init(id: 0, name: "Film")], stopAfter: "scan")
        request.expectedPlanFingerprint = "synthetic-server-plan"
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let raw = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(request))
        #expect(raw["expected_plan_fingerprint"].string == "synthetic-server-plan")
    }
}
