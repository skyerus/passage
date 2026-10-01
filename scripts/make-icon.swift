import AppKit

let destination = URL(fileURLWithPath: CommandLine.arguments[1])
let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".iconset")
try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: temporary) }

for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        let factor = CGFloat(pixels) / 1024
        let transform = NSAffineTransform()
        transform.scale(by: factor)
        transform.concat()
        NSColor(calibratedRed: 0.94, green: 0.91, blue: 0.84, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 48, y: 48, width: 928, height: 928), xRadius: 205, yRadius: 205).fill()
        NSColor(calibratedRed: 0.10, green: 0.30, blue: 0.28, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 190, y: 240, width: 285, height: 540), xRadius: 45, yRadius: 45).fill()
        NSBezierPath(roundedRect: NSRect(x: 550, y: 300, width: 245, height: 425), xRadius: 40, yRadius: 40).fill()
        NSColor(calibratedRed: 0.99, green: 0.98, blue: 0.94, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 221, y: 300, width: 223, height: 445), xRadius: 12, yRadius: 12).fill()
        NSBezierPath(roundedRect: NSRect(x: 578, y: 354, width: 189, height: 340), xRadius: 12, yRadius: 12).fill()
        NSColor(calibratedRed: 0.83, green: 0.55, blue: 0.22, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 247, y: 546, width: 172, height: 27), xRadius: 8, yRadius: 8).fill()
        NSBezierPath(roundedRect: NSRect(x: 600, y: 546, width: 144, height: 27), xRadius: 8, yRadius: 8).fill()
        NSColor(calibratedRed: 0.10, green: 0.30, blue: 0.28, alpha: 0.35).setFill()
        for y in [620, 655, 490, 455] {
            NSBezierPath(roundedRect: NSRect(x: 247, y: y, width: 160, height: 12), xRadius: 5, yRadius: 5).fill()
            NSBezierPath(roundedRect: NSRect(x: 600, y: y, width: 136, height: 12), xRadius: 5, yRadius: 5).fill()
        }
        NSGraphicsContext.restoreGraphicsState()
        let name = "icon_\(size)x\(size)" + (scale == 2 ? "@2x" : "") + ".png"
        try rep.representation(using: .png, properties: [:])!.write(to: temporary.appendingPathComponent(name))
    }
}
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", temporary.path, "-o", destination.path]
try process.run()
process.waitUntilExit()
if process.terminationStatus != 0 { exit(process.terminationStatus) }
