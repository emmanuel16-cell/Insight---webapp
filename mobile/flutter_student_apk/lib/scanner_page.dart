import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:geolocator/geolocator.dart';
import 'package:dio/dio.dart';
import 'api_service.dart';

class ScannerPage extends StatefulWidget {
  const ScannerPage({super.key});

  @override
  State<ScannerPage> createState() => _ScannerPageState();
}

class _ScannerPageState extends State<ScannerPage> {
  bool _isProcessing = false;
  bool _isManualMode = false;
  final _manualCodeController = TextEditingController();
  final MobileScannerController controller = MobileScannerController(
    detectionSpeed: DetectionSpeed.noDuplicates,
    facing: CameraFacing.back,
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scan Attendance'),
        actions: [
          IconButton(
            icon: Icon(_isManualMode ? Icons.camera_alt : Icons.keyboard),
            onPressed: () {
              setState(() {
                _isManualMode = !_isManualMode;
              });
            },
            tooltip: _isManualMode ? 'Switch to Camera' : 'Manual Entry',
          ),
        ],
      ),
      body: Stack(
        children: [
          if (!_isManualMode)
            MobileScanner(
              controller: controller,
              onDetect: (capture) {
                final List<Barcode> barcodes = capture.barcodes;
                if (barcodes.isNotEmpty && !_isProcessing) {
                  final String? code = barcodes.first.rawValue;
                  if (code != null) {
                    _handleScannedCode(code);
                  }
                }
              },
            )
          else
            Padding(
              padding: const EdgeInsets.all(24.0),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.keyboard_outlined, size: 64, color: Color(0xFF2EC4B6)),
                  const SizedBox(height: 24),
                  const Text(
                    'Manual Code Entry',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Enter the session code provided by your instructor.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.grey),
                  ),
                  const SizedBox(height: 32),
                  TextField(
                    controller: _manualCodeController,
                    decoration: InputDecoration(
                      labelText: 'Entry Code',
                      hintText: 'e.g. A3F8B2C1',
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                      prefixIcon: const Icon(Icons.vpn_key_outlined),
                    ),
                    textCapitalization: TextCapitalization.characters,
                  ),
                  const SizedBox(height: 24),
                  SizedBox(
                    width: double.infinity,
                    height: 50,
                    child: ElevatedButton(
                      onPressed: _isProcessing ? null : () => _handleManualSubmit(),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF2EC4B6),
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                      child: const Text('Verify & Submit', style: TextStyle(fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              ),
            ),
          if (!_isManualMode)
            Center(
              child: Container(
                width: 250,
                height: 250,
                decoration: BoxDecoration(
                  border: Border.all(color: const Color(0xFF2EC4B6), width: 4),
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
            ),
          if (_isProcessing)
            Container(
              color: Colors.black54,
              child: const Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: Color(0xFF2EC4B6)),
                    SizedBox(height: 16),
                    Text(
                      'Processing Attendance...',
                      style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                    ),
                  ],
                ),
              ),
            ),
          if (!_isManualMode)
            Positioned(
              bottom: 40,
              left: 0,
              right: 0,
              child: Center(
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Text(
                    'Align QR code within the frame',
                    style: TextStyle(color: Colors.white),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _handleManualSubmit() async {
    final code = _manualCodeController.text.trim();
    if (code.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a code'), backgroundColor: Colors.orange),
      );
      return;
    }
    await _handleScannedCode(code, isManual: true);
  }

  Future<void> _handleScannedCode(String code, {bool isManual = false}) async {
    // Clean code (remove URLs if present)
    if (code.startsWith('http')) {
      try {
        final uri = Uri.parse(code);
        final segments = uri.pathSegments;
        if (segments.isNotEmpty) {
          code = segments.last;
        }
      } catch (_) {}
    }
    
    // Pause camera while processing
    if (!isManual) {
      controller.stop();
    }
    
    setState(() {
      _isProcessing = true;
    });

    try {
      // Check and request location permissions
      bool serviceEnabled;
      LocationPermission permission;

      serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        throw 'Location services are disabled. Please enable them.';
      }

      permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) {
          throw 'Location permissions are denied';
        }
      }

      if (permission == LocationPermission.deniedForever) {
        throw 'Location permissions are permanently denied, we cannot request permissions.';
      }

      // Get location with a timeout
      Position position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.medium,
        timeLimit: const Duration(seconds: 10),
      );

      final response = isManual 
          ? await ApiService().manualScan(code, position.latitude, position.longitude)
          : await ApiService().markAttendance(code, position.latitude, position.longitude);

      if (mounted) {
        final respData = response.data as Map<String, dynamic>;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(respData['message'] ?? 'Attendance marked!'),
            backgroundColor: Colors.green,
          ),
        );
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) {
        String errorMsg = 'Error marking attendance';
        if (e is String) {
          errorMsg = e;
        } else if (e is DioException && e.response?.data is Map) {
          errorMsg = e.response?.data['detail'] ?? errorMsg;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(errorMsg),
            backgroundColor: Colors.red,
          ),
        );
      }
      // Resume scanning after error
      if (!isManual) {
        controller.start();
      }
      setState(() {
        _isProcessing = false;
      });
    }
  }

  @override
  void dispose() {
    _manualCodeController.dispose();
    controller.dispose();
    super.dispose();
  }
}
