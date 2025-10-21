import streamlit as st
import pyodbc
import os
from dotenv import load_dotenv
import hashlib
import datetime
import uuid
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import timedelta

# Load server details
load_dotenv('secrets.env')

# Server variables
server = os.getenv("server")
database = os.getenv("database")
username = os.getenv("dbusername")
password = os.getenv("password")

# Blob storage variables
blob_conn_str = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
blob_container = os.getenv('AZURE_STORAGE_CONTAINER_NAME')
blob_base_url = os.getenv('BLOB_BASE_URL')
blob_service_client = BlobServiceClient.from_connection_string(blob_conn_str)

#AdminVariables
ADMIN_LOGIN_CRED = os.getenv('ADMIN_LOGIN_CRED')
ADMIN_PASS_CRED = os.getenv('ADMIN_PASS_CRED')

# Initialize session state
if 'page' not in st.session_state:
    st.session_state.page = 'login'
if 'agent_id' not in st.session_state:
    st.session_state.agent_id = None
if 'db_id' not in st.session_state:
    st.session_state.db_id = None

# Database connection function
def get_db_connection():
    """Get or create a session-based database connection with validation"""
    if 'db_conn' not in st.session_state or st.session_state.db_conn is None:
        try:
            st.session_state.db_conn = pyodbc.connect(
                "DRIVER={ODBC Driver 17 for SQL Server};SERVER="
                + server
                + ';DATABASE='
                + database
                + ';UID='
                + username
                + ';PWD='
                + password
            )
        except Exception as e:
            st.error(f"Database connection failed: {e}")
            st.session_state.db_conn = None
            return None
    
    # Validate connection
    try:
        cursor = st.session_state.db_conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        return st.session_state.db_conn
    except Exception as e:
        # Connection is invalid, try to reconnect
        try:
            st.session_state.db_conn.close()
        except:
            pass
        try:
            st.session_state.db_conn = pyodbc.connect(
                "DRIVER={ODBC Driver 17 for SQL Server};SERVER="
                + server
                + ';DATABASE='
                + database
                + ';UID='
                + username
                + ';PWD='
                + password
            )
            return st.session_state.db_conn
        except Exception as e:
            st.error(f"Database reconnection failed: {e}")
            st.session_state.db_conn = None
            return None



# Blob storage helper functions
def upload_to_blob(file, document_type, application_ref):
    """Upload file to Azure Blob Storage and return URL with SAS token"""
    if file is None:
        return None, None
    
    try:
        # Generate unique blob name
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        file_extension = file.name.split('.')[-1]
        blob_name = f"{document_type}/{application_ref}_{document_type}_{timestamp}.{file_extension}"
        
        # Upload to blob
        blob_client = blob_service_client.get_blob_client(
            container=blob_container, 
            blob=blob_name
        )
        blob_client.upload_blob(file.getvalue(), overwrite=True)
        
        # Generate SAS token (10 years)
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=blob_container,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.now(datetime.timezone.utc) + timedelta(days=3650)  # 10 years
        )
        
        # Return URL with SAS token and blob name
        blob_url = f"{blob_base_url}/{blob_name}?{sas_token}"
        return blob_url, blob_name
    
    except Exception as e:
        st.error(f"Error uploading {document_type}: {e}")
        return None, None

def get_blob_sas_url(blob_input):
    """Generate a 24-hour SAS URL for a blob given its URL or blob name"""
    if not blob_input:
        return None
    
    try:
        # Extract blob name from URL if full URL
        blob_name = blob_input
        if blob_input.startswith('http'):
            # Parse blob name from full URL
            #URL format: https://account.blob.core.windows.net/container/folder/file.ext?sas_token
            parts = blob_input.split(blob_container + '/')
            if len(parts) > 1:
                blob_name = parts[1].split('?')[0]  # Remove SAS token if present
            else:
                # Try alternative parsing
                # Fallback: just get the path after the last domain part
                url_path = blob_input.split('.net/')[-1]
                blob_name = url_path.split('?')[0]
                # Remove container name if it's at the start
                if blob_name.startswith(f'{blob_container}/'):
                    blob_name = blob_name[len(f'{blob_container}/'):]
        
        # Generate SAS token (24 hours)
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=blob_container,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.now(datetime.timezone.utc) + timedelta(hours=24)
        )
        
        # Return URL with SAS token
        return f"{blob_base_url}/{blob_name}?{sas_token}"
    
    except Exception as e:
        st.error(f"Error generating SAS URL: {e}")
        return None

# Validate file uploads
def validate_file(file, max_size_mb, allowed_extensions):
    """Validate file size and type"""
    if file is None:
        return False, "No file uploaded"
    
    # Check file size
    file_size_mb = file.size / (1024 * 1024)
    if file_size_mb > max_size_mb:
        return False, f"File size exceeds {max_size_mb}MB limit"
    
    # Check file extension
    file_extension = file.name.split('.')[-1].lower()
    if file_extension not in allowed_extensions:
        return False, f"File type .{file_extension} not allowed. Allowed: {', '.join(allowed_extensions)}"
    
    return True, "Valid"

# ============================================================================
# LOGIN PAGE
# ============================================================================
if st.session_state.page == 'login':
    conn = get_db_connection()
    if conn is None:
        st.stop()
    cursor = conn.cursor()
    st.title('Agent Portal Login')
    st.write('Login with your email and password to access the portal.')
    
    with st.form('login_form'):
        email_input = st.text_input('Email', key='login_email')
        password_input = st.text_input('Password', type='password', key='login_password')
        login_button = st.form_submit_button('Login')
        
        if login_button:
            if email_input and password_input:
                # Hash password
                password_hash = hashlib.sha256(password_input.encode()).hexdigest()
                
                try:
                    # Query database with corrected join
                    cursor.execute("""
                        SELECT ac.agent_id, a.id, a.agent_id as agent_string_id, a.application_status
                        FROM agent_credentials ac
                        LEFT JOIN agents a ON ac.agent_id = a.id
                        WHERE ac.email = ? AND ac.password_hash = ? AND ac.is_active = 1
                    """, (email_input, password_hash))
                    
                    row = cursor.fetchone()
                    
                    if row:
                        st.session_state.db_id = row[0]  # Integer agent_id from agent_credentials (references agents.id)
                        st.session_state.agent_id = row[2]  # String agent_id from agents.agent_id
                        st.session_state.email = email_input
                        
                        # Check if they need to complete their profile
                        st.session_state.page = 'dashboard'
                        st.session_state.application_ref = f"APP-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
                        
                        st.rerun()
                    else:
                        st.error('Invalid email or password')
                
                except Exception as e:
                    st.error(f'Login error: {e}')
            else:
                st.warning('Please enter both email and password')
    
    st.write('---')
    st.write('Don\'t have an account?')
    if st.button('Create New Account'):
        st.session_state.page = 'create_account'
        st.rerun()
    st.write('---')
    st.caption('HR/Admin Staff')
    if st.button('Admin Login →'):
        st.session_state.page = 'admin_login'
        st.rerun()

# ============================================================================
# CREATE ACCOUNT PAGE
# ============================================================================
elif st.session_state.page == 'create_account':
    conn = get_db_connection()
    if conn is None:
        st.stop()
    cursor = conn.cursor()
    st.title('Create a New Account')
    st.write('Register to start your agent application process.')
    
    with st.form('create_account_form'):
        email = st.text_input('Email Address', help='Use a valid email address', key='create_email')
        new_password = st.text_input('Password', type='password', help='Minimum 8 characters', key='create_password')
        confirm_password = st.text_input('Confirm Password', type='password', key='create_confirm_password')
        submit_button = st.form_submit_button('Create Account')
        
        if submit_button:
            # Validate inputs
            if not email or not new_password or not confirm_password:
                st.error('Please fill in all fields')
            elif new_password != confirm_password:
                st.error('Passwords do not match')
            elif len(new_password) < 8:
                st.error('Password must be at least 8 characters')
            else:
                try:
                    # Check if email already exists
                    cursor.execute("SELECT email FROM agent_credentials WHERE email = ?", (email,))
                    existing = cursor.fetchone()
                    
                    if existing:
                        st.error('An account with this email already exists')
                    else:
                        # Generate temporary agent ID
                        temp_agent_id = f"TEMP-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
                        application_ref = f"APP-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
                        password_hash = hashlib.sha256(new_password.encode()).hexdigest()
                        created_at = datetime.datetime.now()
                        # Create a minimal agent record (required for foreign key)
                        cursor.execute('''
                            INSERT INTO agents (
                                application_ref, agent_id, first_name, surname, date_of_birth,
                                mobile_number, email, application_status, created_at, created_by
                            )
                            OUTPUT INSERTED.id
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (application_ref, temp_agent_id, 'Pending', 'Completion', 
                            datetime.date(1990, 1, 1), '00000000000', email, 
                            'Incomplete', created_at, email))
                        # Get the auto-generated ID
                        result = cursor.fetchone()
                        if result is None:
                            raise Exception("Failed to retrieve agent ID after insert")
                        
                        agent_db_id = result[0]
                        # Insert into agent_credentials table
                        cursor.execute('''
                            INSERT INTO agent_credentials (
                                agent_id, email, password_hash, is_active, created_at
                            )
                            VALUES (?, ?, ?, ?, ?)
                        ''', (agent_db_id, email, password_hash, 1, created_at))
                        
                        conn.commit()
                        
                        st.success('Account created successfully! Now complete your profile.')
                        st.session_state.agent_id = temp_agent_id
                        st.session_state.db_id = agent_db_id
                        st.session_state.email = email
                        st.session_state.application_ref = application_ref
                        st.session_state.is_new_user = True
                        st.session_state.page = 'agent_info'
                        st.rerun()
                
                except Exception as e:
                    st.error(f'Error creating account: {e}')
                    conn.rollback()
    
    st.write('---')
    if st.button('← Back to Login'):
        st.session_state.page = 'login'
        st.rerun()

# ============================================================================
# AGENT INFORMATION FORM
# ============================================================================
elif st.session_state.page == 'agent_info':
    conn = get_db_connection()
    if conn is None:
        st.stop()
    cursor = conn.cursor()
    st.title('Agent Information Form')
    st.write('Please complete all required fields and upload necessary documents.')
    with st.form('agent_info_form', clear_on_submit=False):
        # Fetch existing agent data to prefill form
        agent_data_prefill = {}
        if st.session_state.db_id:
            try:
                cursor.execute("SELECT * FROM agents WHERE id = ?", (st.session_state.db_id,))
                row = cursor.fetchone()
                if row:
                    columns = [column[0] for column in cursor.description]
                    agent_data_prefill = dict(zip(columns, row))
            except Exception as e:
                st.error(f'Error fetching agent data: {e}')
        
        # Agent ID input
        st.subheader('Agent Identification')
        agent_id_input = st.text_input('Agent ID *', value=agent_data_prefill.get('agent_id', st.session_state.get('agent_id', '')), key='agent_id_input', help='Enter your unique Agent ID')

        # Personal Information
        st.subheader('Personal Information')
        col1, col2 = st.columns(2)
        prefixes = ['Mr', 'Mrs', 'Miss', 'Dr', 'Prof', 'Engr']
        prefix_index = prefixes.index(agent_data_prefill.get('prefix', 'Mr')) if agent_data_prefill.get('prefix') in prefixes else 0
        with col1:
            prefix = st.selectbox('Prefix *', prefixes, index=prefix_index, key='prefix')
            first_name = st.text_input('First Name *', value=agent_data_prefill.get('first_name', ''), key='first_name')

            # Get default date - use prefill if available and valid, otherwise use safe default
            default_dob = agent_data_prefill.get('date_of_birth', datetime.date(1990, 1, 1))
            min_dob = datetime.date(1924, 1, 1)
            max_dob = datetime.date.today() - timedelta(days=365*18)

            # Ensure default is within valid range
            if default_dob < min_dob:
                default_dob = datetime.date(1990, 1, 1)
            elif default_dob > max_dob:
                default_dob = max_dob
            date_of_birth = st.date_input(
                'Date of Birth *', 
                value=default_dob,
                min_value=min_dob,
                max_value=max_dob,
                key='date_of_birth'
            )
            gender_options = ['Male', 'Female', 'Other']
            gender_index = gender_options.index(agent_data_prefill.get('gender', 'Male')) if agent_data_prefill.get('gender') in gender_options else 0
            gender = st.selectbox('Gender *', gender_options, index=gender_index, key='gender')
        with col2:
            surname = st.text_input('Surname *', value=agent_data_prefill.get('surname', ''), key='surname')
            age = (datetime.date.today() - date_of_birth).days // 365
            st.text_input('Age (auto-calculated)', value=str(age), disabled=True, key='age')
            marital_options = ['Single', 'Married', 'Divorced', 'Widowed']
            marital_index = marital_options.index(agent_data_prefill.get('marital_status', 'Single')) if agent_data_prefill.get('marital_status') in marital_options else 0
            marital_status = st.selectbox('Marital Status *', marital_options, index=marital_index, key='marital_status')

        # Contact Information
        st.subheader('Contact Information')
        col3, col4 = st.columns(2)
        with col3:
            mobile_number = st.text_input('Mobile Number *', value=agent_data_prefill.get('mobile_number', ''), key='mobile_number', help='11 digits starting with 0')
            residential_address = st.text_area('Residential Address *', value=agent_data_prefill.get('residential_address', ''), key='residential_address')
            state_list = [
                'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 
                'Benue', 'Borno', 'Cross River', 'Delta', 'Ebonyi', 'Edo', 
                'Ekiti', 'Enugu', 'FCT', 'Gombe', 'Imo', 'Jigawa', 'Kaduna', 
                'Kano', 'Katsina', 'Kebbi', 'Kogi', 'Kwara', 'Lagos', 'Nasarawa', 
                'Niger', 'Ogun', 'Ondo', 'Osun', 'Oyo', 'Plateau', 'Rivers', 
                'Sokoto', 'Taraba', 'Yobe', 'Zamfara'
            ]
            state_index = state_list.index(agent_data_prefill.get('state', 'Lagos')) if agent_data_prefill.get('state') in state_list else 0
            state = st.selectbox('State *', state_list, index=state_index, key='state')
        with col4:
            email_display = st.text_input('Email', value=st.session_state.get('email', ''), disabled=True, key='email_display')
            lga = st.text_input('Local Government Area *', value=agent_data_prefill.get('lga', ''), key='lga')

        # Next of Kin
        st.subheader('Next of Kin')
        col5, col6 = st.columns(2)
        with col5:
            nok_name = st.text_input('Next of Kin Full Name *', value=agent_data_prefill.get('nok_name', ''), key='nok_name')
            nok_relationship_options = ['Spouse', 'Parent', 'Sibling', 'Child', 'Friend', 'Other']
            nok_index = nok_relationship_options.index(agent_data_prefill.get('nok_relationship', 'Spouse')) if agent_data_prefill.get('nok_relationship') in nok_relationship_options else 0
            nok_relationship = st.selectbox('Relationship *', nok_relationship_options, index=nok_index, key='nok_relationship')
        with col6:
            nok_contact = st.text_input('Next of Kin Contact *', value=agent_data_prefill.get('nok_contact', ''), key='nok_contact')

        # Identification
        st.subheader('Identification')
        col7, col8 = st.columns(2)
        with col7:
            id_type_options = ['NIN', 'Driver\'s License', 'International Passport', 'Voter\'s Card']
            id_index = id_type_options.index(agent_data_prefill.get('id_type', 'NIN')) if agent_data_prefill.get('id_type') in id_type_options else 0
            id_type = st.selectbox('ID Type *', id_type_options, index=id_index, key='id_type')
            id_number = st.text_input('ID Number *', value=agent_data_prefill.get('id_number', ''), key='id_number')
        with col8:
            if agent_data_prefill.get('id_document_blob_url'):
                st.write('ID Document already uploaded ✅')
            id_document = st.file_uploader('Upload ID Document *', type=['pdf', 'jpg', 'jpeg', 'png'], help='Max 5MB', key='id_document')

        # Banking Information
        st.subheader('Banking Information')
        col9, col10 = st.columns(2)
        with col9:
            bank_list = [
                'Access Bank', 'Citibank', 'Diamond Bank', 'Ecobank Nigeria', 
                'Fidelity Bank', 'First Bank of Nigeria', 'First City Monument Bank', 
                'Guaranty Trust Bank', 'Heritage Bank', 'Keystone Bank', 'Polaris Bank',
                'Providus Bank', 'Stanbic IBTC Bank', 'Standard Chartered Bank', 
                'Sterling Bank', 'Union Bank of Nigeria', 'United Bank for Africa', 
                'Unity Bank', 'Wema Bank', 'Zenith Bank'
            ]
            bank_index = bank_list.index(agent_data_prefill.get('bank_name', 'Access Bank')) if agent_data_prefill.get('bank_name') in bank_list else 0
            bank_name = st.selectbox('Bank Name *', bank_list, index=bank_index, key='bank_name')
            account_number = st.text_input('Account Number *', value=agent_data_prefill.get('account_number', ''), key='account_number', max_chars=10, help='10 digits')
        with col10:
            account_name = st.text_input('Account Name *', value=agent_data_prefill.get('account_name', ''), key='account_name')

        # Business Information
        st.subheader('Business Information')
        col11, col12 = st.columns(2)
        with col11:
            region_list = ['North', 'South', 'East', 'West', 'Central', 'Multi-Region']
            region_index = region_list.index(agent_data_prefill.get('region', 'North')) if agent_data_prefill.get('region') in region_list else 0
            region = st.selectbox('Region/Zone of Operation *', region_list, index=region_index, key='region')
        with col12:
            preferred_territory = st.text_input('Preferred Territory (Optional)', value=agent_data_prefill.get('preferred_territory', ''), key='preferred_territory')

        # Document Uploads
        st.subheader('Document Uploads')
        col13, col14 = st.columns(2)
        with col13:
            if agent_data_prefill.get('passport_photo_blob_url'):
                st.write('Passport photo already uploaded ✅')
            passport_photo = st.file_uploader('Passport Photograph *', type=['jpg', 'jpeg', 'png'], help='Max 2MB', key='passport_photo')
        with col14:
            if agent_data_prefill.get('address_proof_blob_url'):
                st.write('Address proof already uploaded ✅')
            address_proof = st.file_uploader('Proof of Address *', type=['pdf', 'jpg', 'jpeg', 'png'], help='Max 5MB', key='address_proof')

        # Single submit button
        st.write('---')
        submit_info = st.form_submit_button('Submit Application', use_container_width=True)
        
        if submit_info:
            # Validation
            errors = []
            
            if not agent_id_input:
                errors.append("Agent ID is required")
            if not first_name or not surname:
                errors.append("First name and surname are required")
            if not mobile_number or len(mobile_number) != 11:
                errors.append("Mobile number must be 11 digits")
            if not account_number or len(account_number) != 10:
                errors.append("Account number must be 10 digits")
            if not id_document and not agent_data_prefill.get('id_document_blob_url'):
                errors.append("ID document is required")
            if not passport_photo and not agent_data_prefill.get('passport_photo_blob_url'):
                errors.append("Passport photograph is required")
            if not address_proof and not agent_data_prefill.get('address_proof_blob_url'):
                errors.append("Proof of address is required")
            
            # Validate file uploads
            if passport_photo:
                valid, msg = validate_file(passport_photo, 2, ['jpg', 'jpeg', 'png'])
                if not valid:
                    errors.append(f"Passport photo: {msg}")
            
            if id_document:
                valid, msg = validate_file(id_document, 5, ['pdf', 'jpg', 'jpeg', 'png'])
                if not valid:
                    errors.append(f"ID document: {msg}")
            
            if address_proof:
                valid, msg = validate_file(address_proof, 5, ['pdf', 'jpg', 'jpeg', 'png'])
                if not valid:
                    errors.append(f"Address proof: {msg}")
            
            if errors:
                for error in errors:
                    st.error(error)
            else:
                try:
                    with st.spinner('Uploading documents and submitting application...'):
                        # Get application ref from session or generate new one
                        application_ref = st.session_state.get('application_ref', f"APP-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")
                        
                        # Upload files to blob storage (only if new files provided)
                        id_url = agent_data_prefill.get('id_document_blob_url')
                        id_blob_name = agent_data_prefill.get('id_document_blob_name')
                        if id_document:
                            id_url, id_blob_name = upload_to_blob(id_document, 'id-documents', application_ref)
                        
                        passport_url = agent_data_prefill.get('passport_photo_blob_url')
                        passport_blob_name = agent_data_prefill.get('passport_photo_blob_name')
                        if passport_photo:
                            passport_url, passport_blob_name = upload_to_blob(passport_photo, 'passport-photos', application_ref)
                        
                        address_url = agent_data_prefill.get('address_proof_blob_url')
                        address_blob_name = agent_data_prefill.get('address_proof_blob_name')
                        if address_proof:
                            address_url, address_blob_name = upload_to_blob(address_proof, 'address-proofs', application_ref)
                        
                        if not id_url or not passport_url or not address_url:
                            st.error('Error uploading documents. Please try again.')
                        else:
                            # Update existing agent record using db_id
                            cursor.execute('''
                                UPDATE agents SET
                                    agent_id = ?, prefix = ?, first_name = ?, surname = ?, date_of_birth = ?, age = ?, 
                                    gender = ?, marital_status = ?, mobile_number = ?, residential_address = ?,
                                    state = ?, lga = ?, nok_name = ?, nok_relationship = ?, nok_contact = ?,
                                    id_type = ?, id_number = ?, id_document_blob_url = ?, id_document_blob_name = ?,
                                    bank_name = ?, account_number = ?, account_name = ?, region = ?, 
                                    preferred_territory = ?, passport_photo_blob_url = ?, passport_photo_blob_name = ?,
                                    address_proof_blob_url = ?, address_proof_blob_name = ?,
                                    application_status = ?, submitted_date = ?, updated_at = ?
                                WHERE id = ?
                            ''', (
                                agent_id_input, prefix, first_name, surname, date_of_birth, age, gender, marital_status,
                                mobile_number, residential_address, state, lga, nok_name, nok_relationship,
                                nok_contact, id_type, id_number, id_url, id_blob_name, bank_name,
                                account_number, account_name, region, preferred_territory, passport_url,
                                passport_blob_name, address_url, address_blob_name, 'Pending',
                                datetime.datetime.now(), datetime.datetime.now(), st.session_state.db_id
                            ))
                            
                            conn.commit()
                            
                            # Update session state with new agent ID
                            st.session_state.agent_id = agent_id_input
                            
                            st.success('✅ Application submitted successfully!')
                            st.info(f'Your application reference number is: **{application_ref}**')
                            st.session_state.page = 'profile'
                            st.rerun()
                
                except Exception as e:
                    st.error(f'Error submitting application: {e}')
                    conn.rollback()
    
    st.write('---')
    if st.button('← Logout'):
        st.session_state.clear()
        st.rerun()

# ============================================================================
# DASHBOARD PAGE
# ============================================================================
elif st.session_state.page == 'dashboard':
    st.title('Welcome to your agent dashboard')
    st.success('You have successfully logged in.')
    st.write('Use the navigation options to proceed.')
    st.write('---')
    if st.button('Update My Information'):
        st.session_state.page = 'agent_info'
        st.rerun()
    if st.button('Go to Profile'):
        st.session_state.page = 'profile'
        st.rerun()
    if st.button('Logout'):
        st.session_state.clear()
        st.rerun()

# ============================================================================
# AGENT PROFILE/DASHBOARD
# ============================================================================
elif st.session_state.page == 'profile':
    conn = get_db_connection()
    if conn is None:
        st.stop()
    cursor = conn.cursor()
    st.title('Agent Dashboard')
    st.write(f"Welcome back! **{st.session_state.get('email', '')}**")
    
    # Fetch agent data
    try:
        cursor.execute("""
            SELECT * FROM agents WHERE id = ?
        """, (st.session_state.db_id,))
        
        agent_data = cursor.fetchone()
        
        if agent_data:
            # Get column names
            columns = [column[0] for column in cursor.description]
            agent_dict = dict(zip(columns, agent_data))
            
            # Display status
            status = agent_dict.get('application_status', 'Unknown')
            if status == 'Approved':
                st.success(f'✅ Application Status: **{status}**')
            elif status == 'Pending':
                st.info(f'⏳ Application Status: **{status}**')
            elif status == 'Incomplete':
                st.warning(f'⚠️ Application Status: **{status}** - Please complete your profile')
            else:
                st.warning(f'Application Status: **{status}**')
            
            # Display application reference and agent ID
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Application Reference", agent_dict.get('application_ref', 'N/A'))
            with col2:
                if status == 'Approved' and agent_dict.get('agent_id'):
                    st.metric("Agent ID", agent_dict.get('agent_id', 'N/A'))
                else:
                    st.metric("Agent ID", "Pending Approval")
            with col3:
                submitted_date = agent_dict.get('submitted_date')
                if submitted_date:
                    st.metric("Submitted On", submitted_date.strftime('%Y-%m-%d'))
            
            # If application is incomplete, prompt to complete
            if status == 'Incomplete':
                st.write('---')
                st.warning('Your application is incomplete. Please complete your profile to submit for review.')
                if st.button('Complete Application Form'):
                    st.session_state.page = 'agent_info'
                    st.rerun()
            
            # Show profile details if complete
            elif agent_dict.get('first_name'):
                st.write('---')
                st.subheader('Profile Information')
                
                with st.expander('Personal Information', expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Name:** {agent_dict.get('prefix', '')} {agent_dict.get('first_name', '')} {agent_dict.get('surname', '')}")
                        st.write(f"**Date of Birth:** {agent_dict.get('date_of_birth', 'N/A')}")
                        st.write(f"**Gender:** {agent_dict.get('gender', 'N/A')}")
                    with col2:
                        st.write(f"**Age:** {agent_dict.get('age', 'N/A')}")
                        st.write(f"**Marital Status:** {agent_dict.get('marital_status', 'N/A')}")
                
                with st.expander('Contact Information'):
                    st.write(f"**Mobile:** {agent_dict.get('mobile_number', 'N/A')}")
                    st.write(f"**Email:** {agent_dict.get('email', 'N/A')}")
                    st.write(f"**Address:** {agent_dict.get('residential_address', 'N/A')}")
                    st.write(f"**State:** {agent_dict.get('state', 'N/A')}")
                    st.write(f"**LGA:** {agent_dict.get('lga', 'N/A')}")
                
                with st.expander('Banking Information'):
                    st.write(f"**Bank:** {agent_dict.get('bank_name', 'N/A')}")
                    st.write(f"**Account Number:** {agent_dict.get('account_number', 'N/A')}")
                    st.write(f"**Account Name:** {agent_dict.get('account_name', 'N/A')}")
                
                with st.expander('Documents'):
                    if agent_dict.get('passport_photo_blob_url'):
                        st.write("**Passport Photograph:** ✅ Uploaded")
                    if agent_dict.get('id_document_blob_url'):
                        st.write("**ID Document:** ✅ Uploaded")
                    if agent_dict.get('address_proof_blob_url'):
                        st.write("**Address Proof:** ✅ Uploaded")
        else:
            st.error('Agent profile not found')
    
    except Exception as e:
        st.error(f'Error loading profile: {e}')
    
    st.write('---')
    if st.button('Logout'):
        st.session_state.clear()
        st.rerun()

# ============================================================================
# ADMIN LOGIN PAGE
# ============================================================================
elif st.session_state.page == 'admin_login':
    st.title('HR/Admin Portal Login')
    st.write('Authorized personnel only')
    st.write('Debug: Admin login form rendered')
    
    with st.form('admin_login_form', clear_on_submit=True):
        admin_username = st.text_input('Username', key='admin_username_input')
        admin_password = st.text_input('Password', type='password', key='admin_password_input')
        admin_login_button = st.form_submit_button('Login as Admin', use_container_width=True)
        
        if admin_login_button:
            if admin_username and admin_password:
                # Simple hardcoded admin check (replace with database check later)
                if admin_username == ADMIN_LOGIN_CRED and admin_password == ADMIN_PASS_CRED:  # CHANGE THIS!
                    st.session_state.is_admin = True
                    st.session_state.admin_user = admin_username
                    st.session_state.page = 'admin_dashboard'
                    st.rerun()
                else:
                    st.error('Invalid admin credentials')
            else:
                st.warning('Please enter username and password')
    
    st.write('---')
    if st.button('← Back to Agent Login'):
        st.session_state.page = 'login'
        st.rerun()

# ============================================================================
# TEST PAGE FOR FORM BUTTON
# ============================================================================
elif st.session_state.page == 'test_page':
    st.title('Test Page')
    st.write('This is a test page to verify form button rendering.')
    
    with st.form('test_form', clear_on_submit=True):
        test_input = st.text_input('Test Input', key='test_input')
        test_submit = st.form_submit_button('Test Submit', use_container_width=True)
        
        if test_submit:
            st.success(f'Test form submitted with input: {test_input}')
    
    st.write('---')
    if st.button('Back to Admin Login'):
        st.session_state.page = 'admin_login'
        st.rerun()

# ============================================================================
# ADMIN DASHBOARD
# ============================================================================
elif st.session_state.page == 'admin_dashboard':
    conn = get_db_connection()
    if conn is None:
        st.stop()
    cursor = conn.cursor()
    if not st.session_state.get('is_admin', False):
        st.error("Unauthorized access. Please log in as admin.")
        st.session_state.page = 'admin_login'
        st.rerun()
        st.stop()

    st.title('HR/Admin Dashboard')
    st.write(f"Welcome, {st.session_state.get('admin_user', 'Admin')}")

    # Summary Metrics
    try:
        cursor.execute("SELECT COUNT(*) FROM agents")
        total_apps = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM agents WHERE application_status = 'Pending'")
        pending_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM agents WHERE application_status = 'Approved'")
        approved_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM agents WHERE application_status = 'Incomplete'")
        incomplete_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM agents WHERE application_status = 'Rejected'")
        rejected_count = cursor.fetchone()[0]

        st.subheader("Application Summary")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Applications", total_apps)
        with col2:
            st.metric("Pending Review", pending_count)
        with col3:
            st.metric("Approved", approved_count)
        with col4:
            st.metric("Incomplete", incomplete_count)
        with col5:
            st.metric("Rejected", rejected_count)
    except Exception as e:
        st.error(f"Error fetching metrics: {e}")

    # Filter and Search
    st.subheader("Filter and Search Agents")
    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "Pending", "Approved", "Incomplete", "Rejected"],
            key="status_filter"
        )
    with col2:
        region_list = ['All', 'North', 'South', 'East', 'West', 'Central', 'Multi-Region']
        region_filter = st.selectbox("Filter by Region", region_list, key="region_filter")
    with col3:
        search_query = st.text_input("Search by Name, Email, or Agent ID", key="search_query")

    # Build SQL Query
    query = "SELECT id, first_name, surname, agent_id, email, application_status, state, region, submitted_date FROM agents"
    conditions = []
    params = []

    if status_filter != "All":
        conditions.append("application_status = ?")
        params.append(status_filter)
    if region_filter != "All":
        conditions.append("region = ?")
        params.append(region_filter)
    if search_query:
        conditions.append("(first_name LIKE ? OR surname LIKE ? OR email LIKE ? OR agent_id LIKE ?)")
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term, search_term, search_term])

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    # Agent List
    try:
        cursor.execute(query, params)
        agents = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        agent_data = [dict(zip(columns, row)) for row in agents]

        st.subheader("Agent List")
        if not agent_data:
            st.info("No agents found matching the criteria.")
        else:
            for agent in agent_data:
                status = agent.get('application_status', 'Unknown')
                status_emoji = {
                    'Approved': '🟢',
                    'Pending': '🟡',
                    'Incomplete': '⚪',
                    'Rejected': '🔴'
                }.get(status, '')
                name = f"{agent.get('first_name', '')} {agent.get('surname', '')}".strip()

                with st.expander(f"{status_emoji} {name} ({agent.get('agent_id', 'N/A')})"):
                    st.write(f"**Email:** {agent.get('email', 'N/A')}")
                    st.write(f"**Status:** {status}")
                    st.write(f"**State/Region:** {agent.get('state', 'N/A')}/{agent.get('region', 'N/A')}")
                    submitted_date = agent.get('submitted_date')
                    st.write(f"**Submitted On:** {submitted_date.strftime('%Y-%m-%d') if submitted_date else 'N/A'}")
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("View Details", key=f"view_{agent['id']}"):
                            st.session_state.selected_agent_id = agent['id']
                            st.session_state.page = 'admin_agent_detail'
                            st.rerun()
                    if status == 'Pending':
                        with col2:
                            if st.button("Approve", key=f"approve_{agent['id']}"):
                                try:
                                    cursor.execute(
                                        "UPDATE agents SET application_status = ?, updated_at = ? WHERE id = ?",
                                        ('Approved', datetime.datetime.now(), agent['id'])
                                    )
                                    conn.commit()
                                    st.success(f"Agent {agent['agent_id']} approved")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error approving agent: {e}")
                        with col3:
                            if st.button("Reject", key=f"reject_{agent['id']}"):
                                try:
                                    cursor.execute(
                                        "UPDATE agents SET application_status = ?, updated_at = ? WHERE id = ?",
                                        ('Rejected', datetime.datetime.now(), agent['id'])
                                    )
                                    conn.commit()
                                    st.success(f"Agent {agent['agent_id']} rejected")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error rejecting agent: {e}")
    except Exception as e:
        st.error(f"Error fetching agent list: {e}")

    # Navigation
    st.write('---')
    if st.button('Logout'):
        st.session_state.clear()
        st.rerun()

# ============================================================================
# ADMIN AGENT DETAIL VIEW
# ============================================================================
elif st.session_state.page == 'admin_agent_detail':
    conn = get_db_connection()
    if conn is None:
        st.stop()
    cursor = conn.cursor()
    if not st.session_state.get('is_admin', False):
        st.error("Unauthorized access. Please log in as admin.")
        st.session_state.page = 'admin_login'
        st.rerun()
        st.stop()

    agent_id = st.session_state.get('selected_agent_id')
    if not agent_id:
        st.error("No agent selected")
        st.session_state.page = 'admin_dashboard'
        st.rerun()
        st.stop()

    st.title('Agent Details')
    try:
        cursor.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        agent_data = cursor.fetchone()
        if agent_data:
            columns = [col[0] for col in cursor.description]
            agent = dict(zip(columns, agent_data))
            name = f"{agent.get('prefix', '')} {agent.get('first_name', '')} {agent.get('surname', '')}".strip()
            st.subheader(f"{name} ({agent.get('agent_id', 'N/A')})")
            status = agent.get('application_status', 'Unknown')
            status_emoji = {
                'Approved': '🟢',
                'Pending': '🟡',
                'Incomplete': '⚪',
                'Rejected': '🔴'
            }.get(status, '')
            st.write(f"**Status:** {status_emoji} {status}")
            
            with st.expander("Personal Information", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Name:** {name}")
                    st.write(f"**Date of Birth:** {agent.get('date_of_birth', 'N/A')}")
                    st.write(f"**Gender:** {agent.get('gender', 'N/A')}")
                with col2:
                    st.write(f"**Age:** {agent.get('age', 'N/A')}")
                    st.write(f"**Marital Status:** {agent.get('marital_status', 'N/A')}")

            with st.expander("Contact Information"):
                st.write(f"**Email:** {agent.get('email', 'N/A')}")
                st.write(f"**Mobile:** {agent.get('mobile_number', 'N/A')}")
                st.write(f"**Address:** {agent.get('residential_address', 'N/A')}")
                st.write(f"**State:** {agent.get('state', 'N/A')}")
                st.write(f"**LGA:** {agent.get('lga', 'N/A')}")

            with st.expander("Next of Kin"):
                st.write(f"**Name:** {agent.get('nok_name', 'N/A')}")
                st.write(f"**Relationship:** {agent.get('nok_relationship', 'N/A')}")
                st.write(f"**Contact:** {agent.get('nok_contact', 'N/A')}")

            with st.expander("Identification"):
                st.write(f"**ID Type:** {agent.get('id_type', 'N/A')}")
                st.write(f"**ID Number:** {agent.get('id_number', 'N/A')}")

            with st.expander("Banking Information"):
                st.write(f"**Bank:** {agent.get('bank_name', 'N/A')}")
                st.write(f"**Account Number:** {agent.get('account_number', 'N/A')}")
                st.write(f"**Account Name:** {agent.get('account_name', 'N/A')}")

            with st.expander("Business Information"):
                st.write(f"**Region:** {agent.get('region', 'N/A')}")
                st.write(f"**Preferred Territory:** {agent.get('preferred_territory', 'N/A')}")

            with st.expander("Documents"):
                if agent.get('passport_photo_blob_url'):
                    sas_url = get_blob_sas_url(agent['passport_photo_blob_url'])
                    if sas_url:
                        st.write("**Passport Photograph:**")
                        if agent['passport_photo_blob_url'].lower().endswith(('.jpg', '.jpeg', '.png')):
                            try:
                                st.image(sas_url, width=200)
                            except Exception as e:
                                st.warning(f"Unable to display passport photo: {e}")
                        st.link_button("Download Passport Photo", sas_url)
                    else:
                        st.warning("Unable to generate access URL for passport photo")
                else:
                    st.info("Passport Photograph: Not uploaded")
                
                if agent.get('id_document_blob_url'):
                    sas_url = get_blob_sas_url(agent['id_document_blob_url'])
                    if sas_url:
                        st.write("**ID Document:**")
                        if agent['id_document_blob_url'].lower().endswith(('.jpg', '.jpeg', '.png')):
                            try:
                                st.image(sas_url, width=200)
                            except Exception as e:
                                st.warning(f"Unable to display ID document: {e}")
                        st.link_button("Download ID Document", sas_url)
                    else:
                        st.warning("Unable to generate access URL for ID document")
                else:
                    st.info("ID Document: Not uploaded")
                
                if agent.get('address_proof_blob_url'):
                    sas_url = get_blob_sas_url(agent['address_proof_blob_url'])
                    if sas_url:
                        st.write("**Address Proof:**")
                        if agent['address_proof_blob_url'].lower().endswith(('.jpg', '.jpeg', '.png')):
                            try:
                                st.image(sas_url, width=200)
                            except Exception as e:
                                st.warning(f"Unable to display address proof: {e}")
                        st.link_button("Download Address Proof", sas_url)
                    else:
                        st.warning("Unable to generate access URL for address proof")
                else:
                    st.info("Address Proof: Not uploaded")

            # Actions for Pending status
            if status == 'Pending':
                st.write("---")
                st.subheader("Actions")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Approve Application", key=f"approve_detail_{agent_id}"):
                        try:
                            cursor.execute(
                                "UPDATE agents SET application_status = ?, updated_at = ? WHERE id = ?",
                                ('Approved', datetime.datetime.now(), agent_id)
                            )
                            conn.commit()
                            st.success(f"Agent {agent['agent_id']} approved")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error approving agent: {e}")
                with col2:
                    if st.button("Reject Application", key=f"reject_detail_{agent_id}"):
                        try:
                            cursor.execute(
                                "UPDATE agents SET application_status = ?, updated_at = ? WHERE id = ?",
                                ('Rejected', datetime.datetime.now(), agent_id)
                            )
                            conn.commit()
                            st.success(f"Agent {agent['agent_id']} rejected")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error rejecting agent: {e}")

        else:
            st.error("Agent not found")
            st.session_state.page = 'admin_dashboard'
            st.rerun()
    except Exception as e:
        st.error(f"Error loading agent details: {e}")

    # Navigation
    st.write('---')
    col1, col2 = st.columns(2)
    with col1:
        if st.button('Back to Dashboard'):
            st.session_state.page = 'admin_dashboard'
            st.rerun()
    with col2:
        if st.button('Logout'):
            st.session_state.clear()
            st.rerun()
