#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple Flask app runner
"""
import sys
import os

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

try:
    from app import app, ensure_data_dir
    
    # Initialize database
    with app.app_context():
        ensure_data_dir()
    
    print("=" * 60)
    print("Flask app is running!")
    print("=" * 60)
    print("\nOpen your browser at: http://localhost:5000")
    print("\nLogin with:")
    print("  admin / admin123  (admin role)")
    print("  teacher / 12345   (teacher role)")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)
    
    # Run the app
    app.run(debug=True, host='0.0.0.0', port=5000)
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
