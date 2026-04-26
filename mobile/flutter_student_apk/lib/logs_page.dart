import 'package:flutter/material.dart';
import 'api_service.dart';
import 'package:intl/intl.dart';

class LogsPage extends StatefulWidget {
  const LogsPage({super.key});

  @override
  State<LogsPage> createState() => _LogsPageState();
}

class _LogsPageState extends State<LogsPage> with SingleTickerProviderStateMixin {
  late TabController _tabController;
  List<dynamic> _gateLogs = [];
  List<dynamic> _subjectLogs = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _fetchAllLogs();
  }

  Future<void> _fetchAllLogs() async {
    setState(() => _isLoading = true);
    try {
      final results = await Future.wait([
        ApiService().getGateLogs(),
        ApiService().getSubjectLogs(),
      ]);

      setState(() {
        _gateLogs = List<dynamic>.from(results[0].data ?? []);
        
        // Subject logs: exclude 'absent'
        final subjectData = results[1].data as Map<String, dynamic>?;
        final List<dynamic> allSubjectRecords = List<dynamic>.from(subjectData?['records'] ?? []);
        _subjectLogs = allSubjectRecords.where((log) {
          final status = log['status']?.toString().toLowerCase() ?? 'absent';
          return status != 'absent';
        }).toList();
        
        _isLoading = false;
      });
    } catch (e) {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: 'Gate'),
            Tab(text: 'Subject'),
          ],
          labelColor: const Color(0xFF2EC4B6),
          indicatorColor: const Color(0xFF2EC4B6),
          unselectedLabelColor: Colors.grey,
        ),
        Expanded(
          child: _isLoading 
            ? const Center(child: CircularProgressIndicator())
            : TabBarView(
                controller: _tabController,
                children: [
                  _buildGateLogs(),
                  _buildSubjectLogs(),
                ],
              ),
        ),
      ],
    );
  }

  Widget _buildGateLogs() {
    if (_gateLogs.isEmpty) return _buildEmptyState('No gate logs found');
    
    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: _gateLogs.length,
      separatorBuilder: (context, index) => const Divider(),
      itemBuilder: (context, index) {
        final log = _gateLogs[index];
        final date = log['date'] != null ? DateFormat('MMM dd, yyyy').format(DateTime.parse(log['date'])) : '—';
        
        String formatTime(dynamic t) {
          if (t == null || t == '—' || t == '') return '—';
          try {
            return DateFormat('hh:mm a').format(DateTime.parse(t.toString()));
          } catch (e) {
            return t.toString();
          }
        }

        final checkIn = formatTime(log['check_in']);
        final checkOut = formatTime(log['check_out']);

        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(date, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 12),
              Row(
                children: [
                  _buildGateInfo('IN', checkIn, Icons.login, Colors.green),
                  const SizedBox(width: 16),
                  _buildGateInfo('OUT', checkOut, Icons.logout, Colors.orange),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  _buildStatusChip('Uniform', log['has_uniform'] == 1, Icons.checkroom),
                  const SizedBox(width: 8),
                  _buildStatusChip('ID Card', log['has_id_card'] == 1, Icons.badge),
                ],
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildGateInfo(String label, String time, IconData icon, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: color.withOpacity(0.05),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withOpacity(0.1)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Row(
              children: [
                Icon(icon, size: 14, color: color),
                const SizedBox(width: 4),
                Text(time, style: const TextStyle(fontWeight: FontWeight.w600)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusChip(String label, bool active, IconData icon) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: active ? Colors.blue[50] : Colors.grey[100],
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: active ? Colors.blue : Colors.grey),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              fontSize: 10,
              color: active ? Colors.blue : Colors.grey,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSubjectLogs() {
    if (_subjectLogs.isEmpty) return _buildEmptyState('No subject logs found');

    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: _subjectLogs.length,
      separatorBuilder: (context, index) => const Divider(),
      itemBuilder: (context, index) {
        final log = _subjectLogs[index];
        final status = log['status']?.toString().toLowerCase() ?? 'absent';
        final isPresent = status == 'present' || status == 'late';
        final isOutOfRange = status == 'out_of_range';
        
        final dateStr = log['attendance_date'] != null 
            ? DateFormat('MMM dd, yyyy').format(DateTime.parse(log['attendance_date'])) 
            : '—';
        final timeStr = log['time_in'] != null 
            ? DateFormat('hh:mm a').format(DateTime.parse('2000-01-01T${log['time_in']}')) 
            : '—';

        return ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(log['course_name'] ?? 'Unknown Subject', style: const TextStyle(fontWeight: FontWeight.bold)),
          subtitle: Text('$dateStr • $timeStr • ${log['recognition_method'] ?? 'N/A'}'),
          trailing: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: isPresent ? Colors.green[50] : (isOutOfRange ? Colors.orange[50] : Colors.red[50]),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              status.replaceAll('_', ' ').toUpperCase(),
              style: TextStyle(
                color: isPresent ? Colors.green : (isOutOfRange ? Colors.orange : Colors.red),
                fontSize: 11,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildEmptyState(String message) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.history, size: 64, color: Colors.grey[300]),
          const SizedBox(height: 16),
          Text(message, style: TextStyle(color: Colors.grey[500])),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }
}
