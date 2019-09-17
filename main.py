import string
import random
import requests
from flask import make_response
import json
import httplib2
from oauth2client.client import FlowExchangeError
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import AccessTokenCredentials
from flask import session as login_session
from models import Base, Category, CategoryItem, User
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from flask import Flask, render_template, request, redirect, jsonify, url_for, flash, g
from flask_httpauth import HTTPBasicAuth

app = Flask(__name__)
auth = HTTPBasicAuth()


engine = create_engine('postgresql://catalog:catalog@localhost:5432/catalog')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']

# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in range(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)


@app.route('/oauth/<provider>', methods=['POST'])
def oauth(provider):
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter!'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data
    #print(code)
    if provider == 'google':
        # Upgrade the authorization code into a credentials object
        try:
            oauth_flow = flow_from_clientsecrets(
                'client_secrets.json', scope='')
            oauth_flow.redirect_uri = 'postmessage'
            credentials = oauth_flow.step2_exchange(code)
        except FlowExchangeError:
            response = make_response(json.dumps(
                'Failed to upgrade the authorization code.'), 401)
            response.headers['Content-Type'] = 'application/json'
            return response

        # Check that the access token is valid
        access_token = credentials.access_token
        url = (
            'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s' % access_token)
        h = httplib2.Http()
        result = json.loads(h.request(url, 'GET')[1])
        # If there was an error in the access token info, abort.
        if result.get('error') is not None:
            response = make_response(json.dumps(result.get('error')), 500)
            response.headers['Content-Type'] = 'application/json'
            return response

        # Verify that the access token is used for the intended user.
        google_id = credentials.id_token['sub']
        if result['user_id'] != google_id:
            response = make_response(json.dumps(
                "Token's user ID dopesn't match given user ID."), 401)
            response.headers['Content-Type'] = 'application/json'
            return response

        # Verify that the access token is valid for this app.
        if result['issued_to'] != CLIENT_ID:
            response = make_response(json.dumps(
                "Token's client ID dopesn't match app's."), 401)
            response.headers['Content-Type'] = 'application/json'
            return response

        # Check to see if user is already logged in.
        stored_credentials = login_session.get('credentials')
        stored_google_id = login_session.get('google_id')
        if stored_credentials is not None and google_id == stored_google_id:
            response = make_response(json.dumps(
                'Current user is already connecgted.'), 200)
            response.headers['Content-Type'] = 'application/json'
            return response

        # Store the access token in the session for later use.
        login_session['credentials'] = credentials.access_token
        login_session['google_id'] = google_id

        # Get user info
        userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
        params = {'access_token': credentials.access_token, 'alt': 'json'}
        answer = requests.get(userinfo_url, params=params)

        #data = json.loads(answer.text)
        data = answer.json()

        #print(data)

        login_session['username'] = data["name"]
        login_session['picture'] = data["picture"]
        login_session['email'] = data["email"]
        # ADD PROVIDER TO LOGIN SESSION
        login_session['provider'] = 'google'

        # see if user exists, if it doesn't make new user
        user_id = getUserID(login_session['email'])
        if not user_id:
            user_id = createUser(login_session)
            login_session['user_id'] = user_id

        output = ''
        output += '<h1>Welcome, '
        output += login_session['username']
        output += '!</h1>'
        output += '<img src="'
        output += login_session['picture']
        output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
        flash("you are now logged in as %s" % login_session['username'])
        #print("done!")
        return output

    elif provider == 'facebook':
        if request.args.get('state') != login_session['state']:
            response = make_response(json.dumps(
                'Invalid state parameter.'), 401)
            response.headers['Content-Type'] = 'application/json'
            return response
        access_token = request.data
        #print("access token received %s " % access_token)

        app_id = json.loads(open('fb_client_secrets.json', 'r').read())[
            'web']['app_id']
        app_secret = json.loads(
            open('fb_client_secrets.json', 'r').read())['web']['app_secret']
        url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (
            app_id, app_secret, access_token)
        h = httplib2.Http()
        result = h.request(url, 'GET')[1]

        # Use token to get user info from API
        userinfo_url = "https://graph.facebook.com/v2.8/me"
        '''
            Due to the formatting for the result from the server token exchange we have to
            split the token first on commas and select the first index which gives us the key : value
            for the server access token then we split it on colons to pull out the actual token value
            and replace the remaining quotes with nothing so that it can be used directly in the graph
            api calls
        '''
        token = result.split(',')[0].split(':')[1].replace('"', '')

        url = 'https://graph.facebook.com/v2.8/me?access_token=%s&fields=name,id,email' % token
        h = httplib2.Http()
        result = h.request(url, 'GET')[1]
        #print("url sent for API access:%s"% url)
        #print("API JSON result: %s" % result)
        data = json.loads(result)
        login_session['provider'] = 'facebook'
        login_session['username'] = data["name"]
        login_session['email'] = data["email"]
        login_session['facebook_id'] = data["id"]

        # The token must be stored in the login_session in order to properly logout
        login_session['access_token'] = token

        # Get user picture
        url = 'https://graph.facebook.com/v2.8/me/picture?access_token=%s&redirect=0&height=200&width=200' % token
        h = httplib2.Http()
        result = h.request(url, 'GET')[1]
        data = json.loads(result)

        login_session['picture'] = data["data"]["url"]

        # see if user exists
        user_id = getUserID(login_session['email'])
        if not user_id:
            user_id = createUser(login_session)
        login_session['user_id'] = user_id

        output = ''
        output += '<h1>Welcome, '
        output += login_session['username']

        output += '!</h1>'
        output += '<img src="'
        output += login_session['picture']
        output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '

        flash("Now logged in as %s" % login_session['username'])
        return output
    else:
        return 'Unrecoginized Provider'

# User Helper Functions


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None

# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/fbdisconnect')
def fbdisconnect():
    facebook_id = login_session['facebook_id']
    # The access token must me included to successfully logout
    # access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions' % facebook_id
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]
    del login_session['username']
    del login_session['email']
    del login_session['picture']
    del login_session['user_id']
    del login_session['facebook_id']
    return "you have been logged out"


@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        #print('Access Token is None')
        response = make_response(json.dumps(
            'Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    #print('In gdisconnect access token is %s', access_token)
    #print('User name is: ')
    #print(login_session['username'])
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    #print('result is ')
    #print(result)
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['google_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps(
            'Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response

@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['google_id']
            del login_session['credentials']
        if login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['facebook_id']

        del login_session['username']
        del login_session['email']
        del login_session['picture']
        #del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showCategories'))
    else:
        flash("You have not logged in to begin with!")
        redirect(url_for('showCategories'))


# JSON APIs to view Category Information
@app.route('/categoty/JSON')
def indexJSON():
    categories = session.query(Category).all()
    return jsonify(categoryItems=[i.serialize for i in categories])


@app.route('/categoty/<int:category_id>/items/JSON')
def showCategoryItemsJSON(category_id):
    category = session.query(Category).filter_by(id=category_id).one()
    categoryItems = session.query(CategoryItem).filter_by(
        category_id=category_id).all()
    return jsonify(categoryItems=[i.serialize for i in categoryItems])


@app.route('/categoty/<int:category_id>/items/<int:item_id>/JSON')
def showItemJSON(category_id, item_id):
    categoryItem = session.query(CategoryItem).filter_by(id=item_id).one()
    return jsonify(categoryItem=categoryItem.serialize)


@app.route('/users/<int:id>/JSON')
def get_user(id):
    user = session.query(User).filter_by(id=id).one()
    if not user:
        abort(400)
    return jsonify({'name': user.name})

# Show all Categories
@app.route('/')
@app.route('/catalog')
def showCategories():
    category = ''
    categories = session.query(Category).order_by(Category.name.asc())
    categoryItems = session.query(CategoryItem).all()
    if 'username' not in login_session:
        return render_template('publicCategories.html', category='', categoryItems=categoryItems, categories=categories)
    else:
        return render_template('categories.html', category='', categoryItems=categoryItems, categories=categories)

# Create a new Category
@app.route('/category/new', methods=['GET', 'POST'])
def newCategory():
    if 'username' not in login_session:
        return redirect('/login')
    category = ''
    categories = session.query(Category)
    if request.method == 'POST':
        newCategory = Category(
            name=request.form['name'], user_id=login_session['user_id'])
        session.add(newCategory)
        flash('New Category %s Successfully Created' % newCategory.name)
        session.commit()
        return redirect(url_for('index'))
    else:
        return render_template('newCategory.html', category='', categories=categories)

# Edit a Category
@app.route('/categoty/<int:category_id>/edit', methods=['GET', 'POST'])
def editCategory(category_id):
    categories = session.query(Category)
    editedCategory = session.query(Category).filter_by(id=category_id).one()
    if request.method == 'POST':
        if request.form['name']:
            editedCategory.name = request.form['name']
            return redirect(url_for('index'))
    else:
        return render_template('editCategory.html', category=editedCategory, categories=categories)

# Delete a Category
@app.route('/categoty/<int:category_id>/delete', methods=['GET', 'POST'])
def deleteCategory(category_id):
    categories = session.query(Category)
    categoryToDelete = session.query(Category).filter_by(id=category_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if categoryToDelete.user_id != login_session['user_id']:
        return "<script>function my function() {alert('You are not authorized to delete this restaurant. Please create your own restaurant in order to delete.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        session.delete(categoryToDelete)
        session.commit()
        return redirect(url_for('index', category_id=category_id))
    else:
        return render_template('deleteCategory.html', category=categoryToDelete, categories=categories)

# Show a Category Items
@app.route('/categoty/<int:category_id>/items')
def showCategoryItems(category_id):
    categories = session.query(Category)
    category = session.query(Category).filter_by(id=category_id).one()
    creator = getUserInfo(category.user_id)
    categoryItems = session.query(CategoryItem).filter_by(
        category_id=category_id).all()
    if 'username' not in login_session or creator.id != login_session['user_id']:
        return render_template('publicCategoryItems.html', category=category, categoryItems=categoryItems, category_id=category_id, categories=categories, creator=creator)
    else:
        return render_template('categoryItems.html', category=category, categoryItems=categoryItems, category_id=category_id, categories=categories, creator=creator)

# Create a New Category Item
@app.route('/categoty/<int:category_id>/items/new', methods=['GET', 'POST'])
def newCategoryItem(category_id):
    item = ''
    category = session.query(Category).filter_by(id=category_id).one()
    if request.method == 'POST':
        newCategoryItem = CategoryItem(name=request.form['name'], description=request.form['description'],
                                       price=request.form['price'], size=request.form['size'], color=request.form['color'], category_id=category_id, user_id=category.user_id)
        session.add(newItem)
        session.commit()
        return redirect(url_for('showCategoryItems', category_id=category_id))
    else:
        categories = session.query(Category)
        return render_template('newCategoryItem.html', category_id=category_id, categories=categories, item=item)

# Edit a Category Item
@app.route('/categoty/<int:category_id>/items/<int:item_id>/edit', methods=['GET', 'POST'])
def editCategoryItem(category_id, item_id):
    editedCategoryItem = session.query(
        CategoryItem).filter_by(id=item_id).one()
    if request.method == 'POST':
        if request.form['name']:
            editedCategoryItem.name = request.form['name']
        session.add(editedCategoryItem)
        session.commit()
        return redirect(url_for('showCategoryItems', category_id=category_id, item_id=item_id))
    else:
        categories = session.query(Category)
        return render_template('editCategoryItem.html', category_id=category_id, item_id=item_id, item=editedCategoryItem, categories=categories)

# Delete a Category Item
@app.route('/categoty/<int:category_id>/items/<int:item_id>/delete', methods=['GET', 'POST'])
def deleteCategoryItem(category_id, item_id):
    categoryItemToDelete = session.query(
        CategoryItem).filter_by(id=item_id).one()
    if request.method == 'POST':
        session.delete(categoryItemToDelete)
        session.commit()
        return redirect(url_for('showCategoryItems', category_id=category_id, item_id=item_id))
    else:
        return render_template('deleteCategoryItem.html', category_id=category_id, item_id=item_id, item=categoryItemToDelete)


@auth.verify_password
def verify_password(username_or_token, password):
    user_id = User.verify_auth_token(username_or_token)
    if user_id:
        user = session.query(User).filter_by(id=user_id).one()
    else:
        user = session.query(User).filter_by(
            name=username_or_token).first()
        if not user or not user.verify_password(password):
            return False
    g.user = user
    return True


@app.route('/token')
@auth.login_required
def get_auth_token():
    token = g.user.generate_auth_token()
    return jsonify({'token': token.decode('ascii')})


@app.route('/users', methods=['POST'])
def new_user():
    name = request.json.get('name')
    password = request.json.get('password')
    if name is None or password is None:
        abort(400)

    if session.query(User).filter_by(name=name).first() is not None:
        None
        user = session.query(User).filter_by(name=name).first()
        return jsonify({'message': 'user already exists'}), 200

    user = User(name=name)
    user.hash_password(password)
    session.add(user)
    session.commit()
    return jsonify({'name': user.name}), 201


@app.route('/signup')
def signup():
    return render_template('signup.tml')


@app.route('/profile')
def profile():
    return render_template('profile.html')


if __name__ == '__main__':
    app.secret_key = "super secret key"
    app.debug = True
    app.run()