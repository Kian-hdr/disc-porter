// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "DiscArchive",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "DiscArchive", targets: ["DiscArchive"])],
    targets: [.executableTarget(name: "DiscArchive"),
              .testTarget(name: "DiscArchiveTests", dependencies: ["DiscArchive"], path: "tests/DiscArchiveTests")],
    swiftLanguageModes: [.v6]
)
