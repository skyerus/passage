import AppKit

/// Compile with BrandMarkGeometry.swift; the same vector paths appear in the app.
@main struct IconGenerator {
    static func main() throws {
        let destination = URL(fileURLWithPath: CommandLine.arguments[1])
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".iconset")
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temporary) }

        for size in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let pixels = size * scale
                let png = render(pixels: pixels)
                let name = "icon_\(size)x\(size)" + (scale == 2 ? "@2x" : "") + ".png"
                try png.write(to: temporary.appendingPathComponent(name))
                if pixels == 1024, CommandLine.arguments.count > 2 {
                    try png.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
                }
            }
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
        process.arguments = ["-c", "icns", temporary.path, "-o", destination.path]
        try process.run()
        process.waitUntilExit()
        if process.terminationStatus != 0 { exit(process.terminationStatus) }
    }

    static func render(pixels: Int) -> Data {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                  bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                  isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        let context = NSGraphicsContext.current!.cgContext
        context.scaleBy(x: CGFloat(pixels) / 1000, y: CGFloat(pixels) / 1000)
        context.translateBy(x: 0, y: 1000)
        context.scaleBy(x: 1, y: -1)

        let tile = CGPath(roundedRect: CGRect(x: 50, y: 50, width: 900, height: 900),
                          cornerWidth: 202, cornerHeight: 202, transform: nil)
        context.saveGState()
        context.setShadow(offset: CGSize(width: 0, height: 7), blur: 13,
                          color: CGColor(gray: 0, alpha: 0.23))
        context.addPath(tile)
        context.setFillColor(color(0.07, 0.20, 0.19))
        context.fillPath()
        context.restoreGState()

        context.addPath(tile)
        context.setFillColor(color(23.0 / 255, 63.0 / 255, 56.0 / 255))
        context.fillPath()
        context.addPath(tile)
        context.setStrokeColor(CGColor(gray: 1, alpha: 0.10))
        context.setLineWidth(2)
        context.strokePath()

        context.addPath(BrandMarkGeometry.mark)
        context.setFillColor(color(245.0 / 255, 240.0 / 255, 227.0 / 255))
        context.fillPath()

        NSGraphicsContext.restoreGraphicsState()
        return rep.representation(using: .png, properties: [:])!
    }

    static func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat) -> CGColor {
        CGColor(red: red, green: green, blue: blue, alpha: 1)
    }
}
