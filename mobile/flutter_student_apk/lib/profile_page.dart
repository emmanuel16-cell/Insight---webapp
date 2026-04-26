import 'package:flutter/material.dart';
import 'api_service.dart';

class ProfilePage extends StatefulWidget {
  const ProfilePage({super.key});

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  Map<String, dynamic>? _profile;
  bool _isLoading = true;
  bool _isEditing = false;
  
  // Controllers for editing
  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _contactController = TextEditingController();
  String? _selectedGender;
  String? _selectedDepartment;
  
  // Controllers for password update
  final _currentPwdController = TextEditingController();
  final _newPwdController = TextEditingController();
  final _confirmPwdController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _fetchProfile();
  }

  Future<void> _fetchProfile() async {
    setState(() => _isLoading = true);
    try {
      final response = await ApiService().getProfile();
      if (response.statusCode == 200) {
        setState(() {
          _profile = Map<String, dynamic>.from(response.data ?? {});
          _firstNameController.text = _profile?['first_name'] ?? '';
          _lastNameController.text = _profile?['last_name'] ?? '';
          _contactController.text = _profile?['contact'] ?? '';
          _selectedGender = _profile?['gender'];
          _selectedDepartment = _profile?['department'];
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _handleUpdateProfile() async {
    try {
      final response = await ApiService().updateProfile({
        'first_name': _firstNameController.text,
        'last_name': _lastNameController.text,
        'gender': _selectedGender,
        'department': _selectedDepartment,
        'contact': _contactController.text,
      });
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Profile updated successfully!'), backgroundColor: Colors.green),
        );
        setState(() => _isEditing = false);
        _fetchProfile();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to update profile'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _handleChangePassword() async {
    if (_newPwdController.text != _confirmPwdController.text) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Passwords do not match'), backgroundColor: Colors.red),
      );
      return;
    }

    try {
      final response = await ApiService().changePassword(
        _currentPwdController.text,
        _newPwdController.text,
        _confirmPwdController.text,
      );
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Password changed successfully!'), backgroundColor: Colors.green),
        );
        _currentPwdController.clear();
        _newPwdController.clear();
        _confirmPwdController.clear();
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to change password'), backgroundColor: Colors.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) return const Center(child: CircularProgressIndicator());

    final prefix = _profile?['gender'] == 'Male' ? 'Mr.' : _profile?['gender'] == 'Female' ? 'Ms.' : '';
    final fullName = '$prefix ${_profile?['first_name'] ?? ''} ${_profile?['last_name'] ?? ''}'.trim();
    final role = (_profile?['role'] ?? '').toString().toUpperCase();
    final department = _profile?['department'] ?? '—';
    final courseDisplay = '$role — $department';

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          Stack(
            children: [
              CircleAvatar(
                radius: 50,
                backgroundColor: const Color(0xFF2EC4B6),
                backgroundImage: _profile?['avatar_url'] != null 
                    ? NetworkImage('${ApiService().baseUrl}${_profile!['avatar_url']}') 
                    : null,
                child: _profile?['avatar_url'] == null 
                    ? const Icon(Icons.person, size: 60, color: Colors.white)
                    : null,
              ),
              if (!_isEditing)
                Positioned(
                  bottom: 0,
                  right: 0,
                  child: CircleAvatar(
                    backgroundColor: const Color(0xFF219EBC),
                    radius: 18,
                    child: IconButton(
                      icon: const Icon(Icons.edit, size: 18, color: Colors.white),
                      onPressed: () => setState(() => _isEditing = true),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 16),
          Text(
            fullName,
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
          ),
          Text(
            courseDisplay,
            style: const TextStyle(color: Colors.grey, fontWeight: FontWeight.bold, fontSize: 12),
          ),
          const SizedBox(height: 32),
          
          if (_isEditing) ...[
            _buildTextField(_firstNameController, 'First Name', Icons.person_outline),
            _buildTextField(_lastNameController, 'Last Name', Icons.person_outline),
            _buildDropdownField('Gender', _selectedGender, ['Male', 'Female'], (val) => setState(() => _selectedGender = val)),
            _buildDropdownField('Department', _selectedDepartment, ['BSCS', 'BSED', 'BEED', 'BSHM', 'ACT'], (val) => setState(() => _selectedDepartment = val)),
            _buildTextField(_contactController, 'Contact', Icons.phone_android_outlined),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => setState(() => _isEditing = false),
                    child: const Text('Cancel'),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: ElevatedButton(
                    onPressed: _handleUpdateProfile,
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF2EC4B6), foregroundColor: Colors.white),
                    child: const Text('Save Changes'),
                  ),
                ),
              ],
            ),
          ] else ...[
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10)],
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(child: _buildGridItem('Student ID', _profile?['student_id'] ?? '—')),
                      Expanded(child: _buildGridItem('Course', _profile?['department'] ?? '—')),
                      Expanded(child: _buildGridItem('Year / Section', _profile?['section'] ?? '—')),
                    ],
                  ),
                  const Divider(height: 32),
                  Row(
                    children: [
                      Expanded(child: _buildGridItem('Gender', _profile?['gender'] ?? '—')),
                      Expanded(child: _buildGridItem('Contact', _profile?['contact'] ?? '—')),
                      Expanded(child: _buildGridItem('Role', role)),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 32),
            OutlinedButton.icon(
              onPressed: () => _showPasswordDialog(context),
              icon: const Icon(Icons.lock_outline),
              label: const Text('Update Password'),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF219EBC),
                minimumSize: const Size(double.infinity, 48),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildGridItem(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey, fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        Text(value, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
      ],
    );
  }

  Widget _buildDropdownField(String label, String? value, List<String> options, ValueChanged<String?> onChanged) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: DropdownButtonFormField<String>(
        value: value,
        decoration: InputDecoration(
          labelText: label,
          prefixIcon: Icon(label == 'Gender' ? Icons.person_outline : Icons.business),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        ),
        items: options.map((opt) => DropdownMenuItem(value: opt, child: Text(opt))).toList(),
        onChanged: onChanged,
      ),
    );
  }

  Widget _buildTextField(TextEditingController controller, String label, IconData icon, {bool enabled = true}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: TextField(
        controller: controller,
        enabled: enabled,
        decoration: InputDecoration(
          labelText: label,
          prefixIcon: Icon(icon),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          filled: !enabled,
          fillColor: enabled ? null : Colors.grey[100],
        ),
      ),
    );
  }

  void _showPasswordDialog(BuildContext context) {
    bool obscureCurrent = true;
    bool obscureNew = true;
    bool obscureConfirm = true;

    showDialog(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Change Password'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _buildPwdField(
                  _currentPwdController, 
                  'Current Password',
                  obscureCurrent,
                  () => setDialogState(() => obscureCurrent = !obscureCurrent),
                ),
                _buildPwdField(
                  _newPwdController, 
                  'New Password',
                  obscureNew,
                  () => setDialogState(() => obscureNew = !obscureNew),
                ),
                _buildPwdField(
                  _confirmPwdController, 
                  'Confirm New Password',
                  obscureConfirm,
                  () => setDialogState(() => obscureConfirm = !obscureConfirm),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
            ElevatedButton(
              onPressed: _handleChangePassword,
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF2EC4B6), foregroundColor: Colors.white),
              child: const Text('Update'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPwdField(TextEditingController controller, String label, bool obscure, VoidCallback onToggle) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller,
        obscureText: obscure,
        decoration: InputDecoration(
          labelText: label,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          suffixIcon: IconButton(
            icon: Icon(
              obscure ? Icons.visibility_off : Icons.visibility,
              color: Colors.grey,
              size: 20,
            ),
            onPressed: onToggle,
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _contactController.dispose();
    _currentPwdController.dispose();
    _newPwdController.dispose();
    _confirmPwdController.dispose();
    super.dispose();
  }
}
