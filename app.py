# app.py

import streamlit as st
import sys
from pathlib import Path

# Add src directory to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from src.ui.dashboard import render_dashboard

def main():
    """Main application entry point"""
    try:
        render_dashboard()
    except Exception as e:
        st.error(f"Application Error: {str(e)}")
        st.markdown("### Troubleshooting Tips:")
        st.markdown("""
        1. *Check Gmail Authentication*: Ensure your Gmail API credentials are properly configured
        2. *Database Issues*: Check if the SQLite database is accessible and has proper permissions
        3. *Network Connection*: Verify your internet connection for Gmail API access
        4. *Dependencies*: Make sure all required packages are installed
        """)
        
        # Show error details in expandable section
        with st.expander("🔧 Technical Details"):
            st.code(str(e))
            st.markdown("If the error persists, check the application logs for more details.")

if __name__ == "__main__":
    main()