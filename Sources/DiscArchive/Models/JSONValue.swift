import Foundation

indirect enum JSONValue: Codable, Equatable, Sendable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let x = try? c.decode(Bool.self) { self = .bool(x) }
        else if let x = try? c.decode(Double.self) { self = .number(x) }
        else if let x = try? c.decode(String.self) { self = .string(x) }
        else if let x = try? c.decode([JSONValue].self) { self = .array(x) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .object(let x): try c.encode(x)
        case .array(let x): try c.encode(x)
        case .string(let x): try c.encode(x)
        case .number(let x): try c.encode(x)
        case .bool(let x): try c.encode(x)
        case .null: try c.encodeNil()
        }
    }
    var object: [String: JSONValue] { if case .object(let x) = self { x } else { [:] } }
    var array: [JSONValue] { if case .array(let x) = self { x } else { [] } }
    var string: String { if case .string(let x) = self { x } else { "" } }
    var number: Double? { if case .number(let x) = self { x } else { nil } }
    var bool: Bool { if case .bool(let x) = self { x } else { false } }
    subscript(_ key: String) -> JSONValue {
        get { object[key] ?? .null }
        set { var o = object; o[key] = newValue; self = .object(o) }
    }
    var stableID: String {
        for key in ["id", "disc_id", "index", "title_id", "sequence", "path"] {
            if let value = object[key], value != .null { return key + ":" + value.display }
        }
        return [self["provider"].display, self["title"].display, self["name"].display, self["year"].display].joined(separator: ":")
    }
    var display: String {
        switch self {
        case .string(let x): x
        case .number(let x): x.rounded() == x ? String(format: "%.0f", x) : String(x)
        case .bool(let x): x ? "Yes" : "No"
        case .null: "Not reported"
        case .array(let x): x.map(\.display).joined(separator: ", ")
        case .object: ""
        }
    }
    static func strings(_ values: [String]) -> JSONValue { .array(values.map(Self.string)) }
}

struct ArchiveSettings: Codable, Equatable, Sendable {
    var values: [String: JSONValue] = [:]
    init(values: [String: JSONValue] = [:]) { self.values = values }
    init(from decoder: Decoder) throws { values = try decoder.singleValueContainer().decode([String: JSONValue].self) }
    func encode(to encoder: Encoder) throws { var c = encoder.singleValueContainer(); try c.encode(values) }
    subscript(_ key: String) -> JSONValue { get { values[key] ?? .null } set { values[key] = newValue } }
    var outputRoot: String { get { self["output_root"].string } set { self["output_root"] = .string(newValue) } }
    var autoStart: Bool { get { self["auto_start"].bool } set { self["auto_start"] = .bool(newValue) } }
    var videoCodec: String { get { values["video_codec"]?.string ?? "hevc" } set { self["video_codec"] = .string(newValue) } }
    var quality: Int { get { Int(self["quality"].number ?? 20) } set { self["quality"] = .number(Double(newValue)) } }
    var languages: [String] { get { self["languages"].array.map(\.string) } set { self["languages"] = .strings(newValue) } }
    var revision: Int { Int(self["revision"].number ?? 0) }
    var appearance: String { self["appearance"].string }
    func changes(from original: Self) -> [String: JSONValue] {
        values.filter { key, value in !["revision", "schema_version", "_identity"].contains(key) && original.values[key] != value }
    }
}

enum WorkspaceDestination: String, CaseIterable, Identifiable {
    case discs, queue, library, profiles, settings
    var id: String { rawValue }
    var title: String { rawValue.capitalized }
    var icon: String {
        switch self { case .discs: "opticaldisc"; case .queue: "list.bullet.rectangle"; case .library: "film.stack"; case .profiles: "slider.horizontal.3"; case .settings: "gearshape" }
    }
}
