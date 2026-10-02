import SwiftUI
import AppKit

struct BrandMark: View {
    var body: some View {
        GeometryReader { geometry in
            // Crop the master icon's clear space for the compact sidebar lockup.
            let rect = BrandMarkGeometry.canvas(in: geometry.size)
            Path(BrandMarkGeometry.fitted(BrandMarkGeometry.mark, in: rect)).fill(teal)
        }
        .aspectRatio(BrandMarkGeometry.bounds.width / BrandMarkGeometry.bounds.height, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

enum BrandMenuIcon {
    static let ready = make(ready: true)
    static let offline = make(ready: false)

    private static func make(ready: Bool) -> NSImage {
        let image = NSImage(size: NSSize(width: 22, height: 18), flipped: true) { _ in
            let context = NSGraphicsContext.current!.cgContext
            var rect = BrandMarkGeometry.canvas(in: CGSize(width: 20, height: 14))
            rect.origin.x += 1
            rect.origin.y += 2
            context.setFillColor(NSColor.black.cgColor)
            context.setStrokeColor(NSColor.black.cgColor)
            context.setLineWidth(1)
            for page in [BrandMarkGeometry.page, BrandMarkGeometry.otherPage] {
                context.addPath(BrandMarkGeometry.fitted(page, in: rect))
                if ready { context.fillPath() } else { context.strokePath() }
            }
            context.addPath(BrandMarkGeometry.fitted(BrandMarkGeometry.pageEdges, in: rect))
            context.fillPath()
            return true
        }
        image.isTemplate = true
        return image
    }
}
