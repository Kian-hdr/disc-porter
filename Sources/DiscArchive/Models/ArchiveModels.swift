import Foundation

struct ArchiveTitle: Codable, Identifiable, Equatable, Sendable {
    let id: Int
    var name: String
    var duration: String?
    var size: String?
    var selected: Bool?
    var audioStreams: [Int]?
    var subtitleStreams: [Int]?
    var defaultAudioStream: Int?
    var defaultSubtitleStream: Int?
    var forcedSubtitleStreams: [Int]?
    var overrides: ArchiveSettings?
    var season: Int?
    var episode: Int?
    var year: Int?
}

func decodeTitles(_ raw: JSONValue) -> [ArchiveTitle] {
    guard let data = try? JSONEncoder().encode(raw) else { return [] }
    let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
    return (try? decoder.decode([ArchiveTitle].self, from: data)) ?? []
}

struct ArchiveDisc: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let label: String
    let format: String
    let sourcePath: String
    let driveIndex: Int?
    let identified: Bool
    let collection: String?
    let titles: [ArchiveTitle]
    let message: String
    let kind: String?
    let streamInventory: JSONValue?
    let selectedTitles: [ArchiveTitle]?
}

struct ArchiveJob: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let collection: String
    let kind: String
    let state: String
    let phase: String
    let checkpoint: String
    let stopAfter: String
    let sourcePath: String
    let outputPath: String
    let progress: Double
    let message: String
    let safeToDisconnect: Bool
    let titles: [ArchiveTitle]
    let createdAt: String
    let updatedAt: String
    let phaseProgress: Double?
    let currentTitle: String?
    let processedBytes: Int64?
    let totalBytes: Int64?
    let completedItems: Int?
    let totalItems: Int?
    let elapsedSeconds: Double?
    let throughputBps: Double?
    let etaSeconds: Double?
    let lastProgressAt: String?
    let heartbeatAt: String?
    let stallReason: String?
    let nextCheckpoint: String?
    let pauseRequested: Bool?
    let progressBasis: String?

    let revision: Int?
    let planRevision: Int?
    let settings: ArchiveSettings?
    let artifacts: [JSONValue]?
    let discStreams: JSONValue?
    let reports: [JSONValue]?
    let acceptance: JSONValue?
    let cleanupStatus: JSONValue?
    let queueOrder: Int?
    let checkpointDetail: JSONValue?
    let pendingChanges: JSONValue?
    let effectiveSettings: JSONValue?
    let generation: Int?

    var originalOnly: Bool {
        if let effectiveSettings, !effectiveSettings.object.isEmpty { return effectiveSettings.object.values.allSatisfy { $0["mode"].string == "original" } }
        return settings?["mode"].string == "original"
    }
    var isActive: Bool { ["running", "queued"].contains(state) }
    var canResume: Bool { ["paused", "blocked", "failed", "waiting_media", "waiting_destination", "waiting_power", "waiting_space"].contains(state) }
}

struct EngineStatus: Codable, Equatable, Sendable {
    let settings: ArchiveSettings
    let jobs: [ArchiveJob]
    let discs: [ArchiveDisc]
    let tools: [String: String?]
    let safeToDisconnect: Bool
    let message: String
    let apiVersion: Int?
    let engineVersion: String?
    let disconnectFenced: Bool?
    let storage: JSONValue?
    let presets: [JSONValue]?
}

struct ScanReply: Decodable, Sendable { let discs: [ArchiveDisc] }
struct Endpoint: Decodable, Sendable { let url: String; let token: String }
struct EngineError: Decodable { let error: String }
struct JobRequest: Encodable, Sendable {
    let sourcePath: String
    let discId: String?
    let collection: String
    let kind: String
    let titles: [ArchiveTitle]
    let stopAfter: String
    var presetId: String? = nil
    var overrides: ArchiveSettings? = nil
    var expectedSettingsRevision: Int? = nil
    var expectedPlanFingerprint: String? = nil
    var idempotencyKey: String? = nil
    var rememberProfile: Bool? = nil
    var metadata: JSONValue? = nil
    var confirmTransforms: Bool? = nil
}
struct ProfileRequest: Encodable, Sendable {
    let discId: String
    let collection: String
    let kind: String
    let titles: [ArchiveTitle]
}
struct JobAction: Encodable, Sendable {
    let action: String
    var stopAfter: String? = nil
    var expectedRevision: Int? = nil
}

enum Checkpoint: String, CaseIterable, Identifiable {
    case scan, acquire, encode, verify, complete
    var id: String { rawValue }
    var title: String {
        switch self {
        case .scan: "Disc identified"
        case .acquire: "Originals saved"
        case .encode: "Candidates encoded"
        case .verify: "Files checked"
        case .complete: "All automatic steps"
        }
    }
    var explanation: String {
        switch self {
        case .scan: "Title selection and destination recorded."
        case .acquire: "Complete originals saved. The disc can be removed after extraction has finished."
        case .encode: "Candidates created with the effective recipe."
        case .verify: "Automatic stream and full decode checks finished."
        case .complete: "Automatic processing finished. Playback and content review remain separate."
        }
    }
}
