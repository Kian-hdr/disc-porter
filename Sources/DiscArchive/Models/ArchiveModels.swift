import Foundation

struct ArchiveSettings: Codable, Equatable, Sendable {
    var outputRoot = ""
    var autoStart = false
    var videoCodec = "hevc"
    var quality = 18
    var languages = ["eng", "deu"]
}

struct ArchiveTitle: Codable, Identifiable, Equatable, Sendable {
    let id: Int
    var name: String
    var duration: String?
    var size: String?
    var selected: Bool?
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

    var isActive: Bool { ["running", "queued"].contains(state) }
    var canResume: Bool { ["paused", "blocked", "failed"].contains(state) }
}

struct EngineStatus: Codable, Equatable, Sendable {
    let settings: ArchiveSettings
    let jobs: [ArchiveJob]
    let discs: [ArchiveDisc]
    let tools: [String: String?]
    let safeToDisconnect: Bool
    let message: String
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
}

enum Checkpoint: String, CaseIterable, Identifiable {
    case scan, acquire, encode, verify, complete
    var id: String { rawValue }
    var title: String {
        switch self {
        case .scan: "Disc identified"
        case .acquire: "Originals saved"
        case .encode: "MP4s encoded"
        case .verify: "Files checked"
        case .complete: "All automatic steps"
        }
    }
    var explanation: String {
        switch self {
        case .scan: "Title selection and destination recorded."
        case .acquire: "Complete originals saved. The disc can be removed after extraction has finished."
        case .encode: "MP4 candidates created. Originals remain available."
        case .verify: "Automatic stream and full decode checks finished."
        case .complete: "Automatic processing finished. Playback and content review remain separate."
        }
    }
}
