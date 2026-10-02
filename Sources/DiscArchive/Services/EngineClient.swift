import Foundation

enum ArchiveClientError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { text } else { nil } }
}

@MainActor
final class EngineClient {
    static let stateDirectory: URL = {
        if let override = ProcessInfo.processInfo.environment["DISC_PORTER_STATE_DIR"] {
            return URL(fileURLWithPath: override, isDirectory: true)
        }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("DiscPorter", isDirectory: true)
    }()
    private var process: Process?
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 90
        return URLSession(configuration: config)
    }()

    private func endpoint() throws -> Endpoint {
        let file = Self.stateDirectory.appendingPathComponent("endpoint.json")
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600,
              (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid() else {
            throw ArchiveClientError.message("The engine endpoint must be a private file owned by this user. Restart Disc Porter.")
        }
        let value = try JSONDecoder().decode(Endpoint.self, from: Data(contentsOf: file))
        guard let url = URL(string: value.url), url.scheme == "http", url.host == "127.0.0.1",
              url.port != nil, url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              ["", "/"].contains(url.path), !value.token.isEmpty else {
            throw ArchiveClientError.message("The local engine connection is invalid. Restart the app.")
        }
        return value
    }

    func ensureRunning() async throws {
        if let status = try? await get("/status", as: EngineStatus.self) {
            guard status.apiVersion == 2, status.engineVersion == "0.2.0" else {
                throw ArchiveClientError.message("An older engine is still running. Finish or pause its jobs, then shut it down with that version before reopening Disc Porter. Active processing is preserved.")
            }
            _ = try await capabilities()
            return
        }
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/DiscPorterHelper/disc-porter-helper")
        let executable: URL
        let arguments: [String]
        if FileManager.default.isExecutableFile(atPath: helper.path) {
            executable = helper
            arguments = ["serve", "--state-dir", Self.stateDirectory.path]
        } else if Bundle.main.object(forInfoDictionaryKey: "DiscPorterSourceRoot") != nil,
                  let script = Bundle.main.resourceURL?.appendingPathComponent("engine/server.py"),
                  FileManager.default.fileExists(atPath: script.path),
                  let python = ["/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.12", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"].first(where: { FileManager.default.isExecutableFile(atPath: $0) }) {
            executable = URL(fileURLWithPath: python)
            arguments = [script.path, "--state-dir", Self.stateDirectory.path]
        } else {
            throw ArchiveClientError.message("The bundled processing helper is missing. Reinstall Disc Porter or rebuild its app package.")
        }
        try FileManager.default.createDirectory(at: Self.stateDirectory, withIntermediateDirectories: true,
                                              attributes: [.posixPermissions: 0o700])
        let log = Self.stateDirectory.appendingPathComponent("engine.log")
        if !FileManager.default.fileExists(atPath: log.path) {
            FileManager.default.createFile(atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let handle = try FileHandle(forWritingTo: log)
        try handle.seekToEnd()
        let child = Process()
        child.executableURL = executable
        child.arguments = arguments
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["PYTHONUNBUFFERED"] = "1"
        child.environment = env
        child.standardOutput = handle
        child.standardError = handle
        child.standardInput = FileHandle.nullDevice
        try child.run()
        process = child
        for _ in 0..<60 {
            try await Task.sleep(for: .milliseconds(250))
            if let status = try? await get("/status", as: EngineStatus.self) {
            guard status.apiVersion == 2, status.engineVersion == "0.2.0" else {
                throw ArchiveClientError.message("An older engine is still running. Finish or pause its jobs, then shut it down with that version before reopening Disc Porter. Active processing is preserved.")
            }
            _ = try await capabilities()
            return
        }
            if !child.isRunning { break }
        }
        throw ArchiveClientError.message("The engine could not start. Check the engine log in Application Support/DiscPorter.")
    }

    func capabilities() async throws -> JSONValue { try await api("GET", "/capabilities") }
    func api(_ method: String, _ path: String, body: [String: JSONValue]? = nil) async throws -> JSONValue {
        let raw = try body.map { try JSONEncoder().encode($0) }
        return try JSONDecoder().decode(JSONValue.self, from: await data(path, body: raw, method: method))
    }
    func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        try await send(path, body: nil, as: type)
    }
    func post<B: Encodable, T: Decodable>(_ path: String, body: B, as type: T.Type) async throws -> T {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try await send(path, body: encoder.encode(body), as: type)
    }
    func postDiscarding<B: Encodable>(_ path: String, body: B) async throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        _ = try await data(path, body: encoder.encode(body))
    }
    func report(_ id: String) async throws -> String {
        let raw = try await data("/report/\(id)", body: nil)
        let object = try JSONSerialization.jsonObject(with: raw)
        let pretty = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
        return String(decoding: pretty, as: UTF8.self)
    }
    private func send<T: Decodable>(_ path: String, body: Data?, as type: T.Type) async throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: await data(path, body: body))
    }
    private func data(_ path: String, body: Data?, method: String? = nil) async throws -> Data {
        let connection = try endpoint()
        guard let url = URL(string: connection.url + path) else {
            throw ArchiveClientError.message("Invalid local request.")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method ?? (body == nil ? "GET" : "POST")
        request.httpBody = body
        request.setValue("Bearer \(connection.token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (result, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else {
            let error = try? JSONDecoder().decode(EngineError.self, from: result)
            throw ArchiveClientError.message(error?.error ?? "The local engine request failed. Try again.")
        }
        return result
    }
}
