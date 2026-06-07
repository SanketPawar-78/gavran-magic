# Gavran Magic - Deployment Guide (Free Tier)

This guide will help you deploy your full-stack application for free using **Render** (Backend), **MongoDB Atlas** (Database), and **GitHub Pages** (Frontend).

---

## 1. Database (MongoDB Atlas)

Since you are deploying to the cloud, you cannot use `localhost`. You need a cloud database.

1.  Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) and sign up for a free account.
2.  Create a **FREE Shared Cluster**.
3.  **Network Access**: Allow access from anywhere (IP `0.0.0.0/0`).
4.  **Database Access**: Create a database user (username/password).
5.  **Get Connection String**:
    *   Click "Connect" > "Connect your application".
    *   Copy the connection string (e.g., `mongodb+srv://user:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority`).
    *   Replace `<password>` with your actual password.

---

## 2. Backend Deployment (Render)

We will deploy the Flask API on Render's free tier.

1.  Push your code to **GitHub**.
2.  Sign up at [Render.com](https://render.com/).
3.  Click **"New +"** -> **"Web Service"**.
4.  Connect your GitHub repository (`gavran-magic`).
5.  **Configure Service**:
    *   **Name**: `gavran-backend` (or similar).
    *   **Region**: Closest to you (e.g., Singapore).
    *   **Branch**: `main`.
    *   **Root Directory**: Leave blank (defaults to root).
    *   **Runtime**: **Python 3**.
    *   **Build Command**: `pip install -r requirements.txt`.
    *   **Start Command**: `gunicorn --chdir backend app:app`.
6.  **Environment Variables**:
    *   Scroll down to "Environment Variables" and add:
        *   `MONGO_URI`: (Your MongoDB Atlas connection string from Step 1)
        *   `JWT_SECRET`: (Any random secret string)
        *   `SHIPROCKET_EMAIL`: (Your email)
        *   `SHIPROCKET_PASSWORD`: (Your password)
        *   `PYTHON_VERSION`: `3.10.0` (Recommended)
7.  Click **"Create Web Service"**.
8.  **Wait for Deployment**: Once live, copy your backend URL (e.g., `https://gavran-backend.onrender.com`).

---

## 3. Frontend Deployment (GitHub Pages)

Now we connect the frontend to the live backend.

1.  Open `frontend-react` folder in your terminal.
2.  Create a file named `.env.production` inside `frontend-react/`.
3.  Add the following line, replacing the URL with your **Render Backend URL**:
    ```env
    VITE_API_BASE_URL=https://gavran-backend.onrender.com
    ```
4.  Deploy the frontend:
    ```bash
    npm run deploy
    ```
    *(This command builds the project and uploads it to GitHub Pages)*.
5.  Your frontend will be live at: `https://SanketPawar-78.github.io/gavran-magic/`

---

### Troubleshooting

-   **CORS Issues**: If the frontend cannot talk to the backend, ensure your backend allows the frontend URL.
-   **White Screen on Frontend**: Check the console (F12) for errors. Ensure the `base` path in `vite.config.js` matches your repository name (`/gavran-magic/`).

