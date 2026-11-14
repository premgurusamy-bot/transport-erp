// Camera QR scanning of package labels. The QR contains only the opaque label (no customer details).
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

class ScanPage extends StatefulWidget {
  const ScanPage({super.key});
  @override
  State<ScanPage> createState() => _ScanPageState();
}

class _ScanPageState extends State<ScanPage> {
  bool done = false;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Scan package label')),
        body: MobileScanner(onDetect: (capture) {
          if (done) return;
          final value = capture.barcodes.isNotEmpty ? capture.barcodes.first.rawValue : null;
          if (value != null && value.isNotEmpty) {
            done = true;
            Navigator.of(context).pop(value);
          }
        }),
      );
}
