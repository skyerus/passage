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

        context.saveGState()
        context.addPath(tile)
        context.clip()
        let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                                  colors: [color(0.16, 0.36, 0.32), color(0.055, 0.19, 0.18)] as CFArray,
                                  locations: [0, 1])!
        context.drawLinearGradient(gradient, start: CGPoint(x: 190, y: 50),
                                   end: CGPoint(x: 800, y: 950), options: [])
        context.restoreGState()
        context.addPath(tile)
        context.setStrokeColor(CGColor(gray: 1, alpha: 0.12))
        context.setLineWidth(2)
        context.strokePath()

        context.saveGState()
        context.setShadow(offset: CGSize(width: 0, height: 4), blur: 5,
                          color: CGColor(gray: 0, alpha: 0.13))
        context.addPath(BrandMarkGeometry.page)
        context.setFillColor(color(0.96, 0.93, 0.85))
        context.fillPath()
        context.addPath(BrandMarkGeometry.otherPage)
        context.setFillColor(color(1.0, 0.98, 0.92))
        context.fillPath()
        context.restoreGState()
        context.addPath(BrandMarkGeometry.bookmark)
        context.setFillColor(color(0.88, 0.68, 0.36))
        context.fillPath()

        NSGraphicsContext.restoreGraphicsState()
        return rep.representation(using: .png, properties: [:])!
    }

    static func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat) -> CGColor {
        CGColor(red: red, green: green, blue: blue, alpha: 1)
    }
}
