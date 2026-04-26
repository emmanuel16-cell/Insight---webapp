import 'package:flutter/material.dart';
import 'api_service.dart';

class SubjectsPage extends StatefulWidget {
  const SubjectsPage({super.key});

  @override
  State<SubjectsPage> createState() => _SubjectsPageState();
}

class _SubjectsPageState extends State<SubjectsPage> {
  List<dynamic> _subjects = [];
  bool _isLoading = true;
  final _joinCodeController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _fetchSubjects();
  }

  Future<void> _fetchSubjects() async {
    setState(() => _isLoading = true);
    try {
      final results = await Future.wait([
        ApiService().getMySubjects(),
        ApiService().getMyEnrollments(),
      ]);

      if (results[0].statusCode == 200 && results[1].statusCode == 200) {
        setState(() {
          final enrolled = List<dynamic>.from(results[0].data ?? []);
          final allEnrollments = List<dynamic>.from(results[1].data ?? []);
          
          // Use join_code or enroll_code as unique key
          final Map<String, dynamic> combinedMap = {};
          
          // Add all from allEnrollments first (mostly pending)
          for (var e in allEnrollments) {
            final code = e['enroll_code'] ?? e['join_code'];
            if (code != null) {
              combinedMap[code] = e;
            }
          }
          
          // Add/Overwrite with enrolled subjects (contains attendance data)
          for (var e in enrolled) {
            final code = e['join_code'] ?? e['enroll_code'];
            if (code != null) {
              combinedMap[code] = e;
            }
          }
          
          _subjects = combinedMap.values.toList();
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _handleEnroll() async {
    final code = _joinCodeController.text.trim();
    if (code.isEmpty) return;

    try {
      final response = await ApiService().enrollSubject(code);
      if (mounted) {
        final respData = response.data as Map<String, dynamic>;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(respData['message'] ?? 'Enrollment request sent!'),
            backgroundColor: Colors.green,
          ),
        );
        _joinCodeController.clear();
        Navigator.pop(context);
        _fetchSubjects();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Failed to enroll. Please check the join code.'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showEnrollDialog(context),
        backgroundColor: const Color(0xFF2EC4B6),
        child: const Icon(Icons.add, color: Colors.white),
      ),
      body: RefreshIndicator(
        onRefresh: _fetchSubjects,
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _subjects.isEmpty
                ? _buildEmptyState()
                : ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _subjects.length,
                    itemBuilder: (context, index) {
                      final subject = _subjects[index];
                      final status = subject['status']?.toString().toLowerCase() ?? 'pending';
                      final isEnrolled = status == 'enrolled';
                      final attendancePct = (subject['attendance_pct'] ?? 0.0).toDouble();
                      final presentCount = subject['present_count'] ?? 0;
                      final absentCount = subject['absent_count'] ?? 0;
                      final totalSessions = subject['total_sessions'] ?? 0;
                      
                      final bool isLowAttendance = isEnrolled && attendancePct < 80.0;
                      final Color themeColor = isLowAttendance ? Colors.orange : const Color(0xFF2EC4B6);
                      final String headerLabel = isEnrolled 
                          ? (attendancePct >= 95 ? 'Perfect Attendance' : (isLowAttendance ? 'Warning: Low Attendance' : 'Good Attendance'))
                          : 'Enrollment Pending';
                      final IconData headerIcon = isEnrolled 
                          ? (isLowAttendance ? Icons.warning : Icons.check_circle_outline)
                          : Icons.hourglass_empty;

                      return Container(
                        margin: const EdgeInsets.only(bottom: 20),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                            color: themeColor.withOpacity(0.5),
                            width: 2,
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            // Card Header
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                              child: Row(
                                children: [
                                  Icon(headerIcon, size: 16, color: themeColor),
                                  const SizedBox(width: 6),
                                  Text(
                                    headerLabel,
                                    style: TextStyle(
                                      color: themeColor,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 13,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            
                            // Subject Info
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    subject['name'] ?? 'Unknown Subject',
                                    style: const TextStyle(
                                      fontSize: 22,
                                      fontWeight: FontWeight.w900,
                                      color: Color(0xFF023047),
                                    ),
                                  ),
                                  Text(
                                    'Instructor: ${subject['instructor_name'] ?? 'N/A'}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.bold,
                                      color: Color(0xFF023047),
                                    ),
                                  ),
                                  
                                  const SizedBox(height: 24),
                                  
                                  // Progress Section
                                  Text(
                                    isEnrolled ? '$presentCount/$totalSessions Classes' : 'Request Sent',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w900,
                                      color: Color(0xFF023047),
                                    ),
                                  ),
                                  const SizedBox(height: 8),
                                  Stack(
                                    children: [
                                      Container(
                                        height: 6,
                                        width: double.infinity,
                                        decoration: BoxDecoration(
                                          color: Colors.grey[200],
                                          borderRadius: BorderRadius.circular(3),
                                        ),
                                      ),
                                      FractionallySizedBox(
                                        widthFactor: (attendancePct / 100).clamp(0.0, 1.0),
                                        child: Container(
                                          height: 6,
                                          decoration: BoxDecoration(
                                            color: themeColor,
                                            borderRadius: BorderRadius.circular(3),
                                          ),
                                        ),
                                      ),
                                      Align(
                                        alignment: Alignment.centerRight,
                                        child: Padding(
                                          padding: const EdgeInsets.only(top: 0),
                                          child: Transform.translate(
                                            offset: const Offset(0, -6),
                                            child: Text(
                                              '${attendancePct.toStringAsFixed(0)}%',
                                              style: TextStyle(
                                                color: themeColor,
                                                fontWeight: FontWeight.w900,
                                                fontSize: 16,
                                              ),
                                            ),
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                  
                                  const SizedBox(height: 12),
                                  const Divider(color: Color(0xFF023047), thickness: 2),
                                  const SizedBox(height: 8),
                                  
                                  // Stats Row
                                  Row(
                                    mainAxisAlignment: MainAxisAlignment.spaceAround,
                                    children: [
                                      _buildCompactStat('Present', '$presentCount', Colors.green),
                                      _buildCompactStat('Absent', '$absentCount', Colors.red),
                                      _buildCompactStat('Required', '80%', const Color(0xFF023047)),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.book_outlined, size: 64, color: Colors.grey[300]),
          const SizedBox(height: 16),
          const Text('No subjects enrolled yet', style: TextStyle(color: Colors.grey)),
          const SizedBox(height: 8),
          const Text('Use the + button to enroll with a join code', style: TextStyle(color: Colors.grey, fontSize: 12)),
        ],
      ),
    );
  }

  Widget _buildCompactStat(String label, String value, Color color) {
    return Column(
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w900,
            color: Color(0xFF023047),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w900,
            color: color,
          ),
        ),
      ],
    );
  }

  void _showEnrollDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Enroll in Subject'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Enter the join code provided by your instructor.'),
            const SizedBox(height: 16),
            TextField(
              controller: _joinCodeController,
              decoration: InputDecoration(
                labelText: 'Join Code',
                hintText: 'e.g. ABC123',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              ),
              textCapitalization: TextCapitalization.characters,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              _joinCodeController.clear();
              Navigator.pop(context);
            },
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: _handleEnroll,
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF2EC4B6),
              foregroundColor: Colors.white,
            ),
            child: const Text('Enroll'),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _joinCodeController.dispose();
    super.dispose();
  }
}
