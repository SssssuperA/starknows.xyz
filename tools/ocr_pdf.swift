import Foundation
import PDFKit
import Vision
import AppKit

// Local OCR: the PDF remains on this machine. Emit one JSON object per page.
let args = CommandLine.arguments
guard args.count >= 3, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    fputs("usage: ocr_pdf PDF PAGE[,PAGE...]\n", stderr)
    exit(1)
}
for n in args[2].split(separator: ",").compactMap({Int($0)}) {
    autoreleasepool {
        guard let page = doc.page(at: n-1) else { return }
        let rect = page.bounds(for: .mediaBox)
        let scale = min(2.5, 2400 / max(rect.width, rect.height))
        let img = page.thumbnail(of: NSSize(width: rect.width*scale,height: rect.height*scale), for: .mediaBox)
        var imageRect = CGRect(origin: .zero, size: img.size)
        guard let cg = img.cgImage(forProposedRect: &imageRect, context: nil, hints: nil) else { return }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        request.usesLanguageCorrection = true
        do {
            try VNImageRequestHandler(cgImage: cg).perform([request])
            let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
            let value: [String:Any] = ["page": n, "text": lines.joined(separator:"\n"), "method":"local-vision-ocr"]
            let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
            print(String(data:data,encoding:.utf8)!)
            fflush(stdout)
        } catch { fputs("OCR failed page \(n): \(error)\n", stderr) }
    }
}
