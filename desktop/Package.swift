// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "ReaderBridge", platforms: [.macOS(.v13)], products: [.executable(name: "ReaderBridge", targets: ["ReaderBridge"])], targets: [.executableTarget(name: "ReaderBridge"), .testTarget(name: "ReaderBridgeTests", dependencies: ["ReaderBridge"])])
