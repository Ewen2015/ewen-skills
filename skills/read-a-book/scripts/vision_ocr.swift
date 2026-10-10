// Page-by-page OCR via Apple's Vision framework. No third-party dependency:
// Vision ships with macOS, so a scanned book costs a compile + a render,
// not an install.
//
// usage: vision_ocr <outfile> <first-page-number> <image> [image...]
//
// Emits one `<<<PDFPAGE n>>>` block per image so the caller can concatenate
// chunks and keep every line citable back to a page.

import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 4 else {
    FileHandle.standardError.write("usage: vision_ocr <outfile> <first-page> <img>...\n".data(using: .utf8)!)
    exit(2)
}
let outPath = args[1]
guard let firstPage = Int(args[2]) else {
    FileHandle.standardError.write("first-page must be an integer\n".data(using: .utf8)!)
    exit(2)
}

var out = ""
for (offset, path) in args[3...].enumerated() {
    let page = firstPage + offset
    out += "\n<<<PDFPAGE \(page)>>>\n"

    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        out += "[无法读取该页图像]\n"
        continue
    }

    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["zh-Hans", "en-US"]
    req.usesLanguageCorrection = true

    do {
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    } catch {
        out += "[OCR 失败: \(error)]\n"
        continue
    }

    // Vision returns observations in no useful order. Sort by (row, column)
    // with a row tolerance, otherwise a two-column page interleaves.
    let lines = (req.results ?? []).compactMap { o -> (CGFloat, CGFloat, String)? in
        guard let c = o.topCandidates(1).first else { return nil }
        let bb = o.boundingBox
        return (1.0 - bb.origin.y, bb.origin.x, c.string)
    }.sorted { a, b in
        abs(a.0 - b.0) < 0.008 ? a.1 < b.1 : a.0 < b.0
    }
    out += lines.map { $0.2 }.joined(separator: "\n") + "\n"
}

do {
    try out.write(toFile: outPath, atomically: true, encoding: .utf8)
} catch {
    FileHandle.standardError.write("cannot write \(outPath): \(error)\n".data(using: .utf8)!)
    exit(1)
}
print("wrote \(outPath) \(out.count) chars")
