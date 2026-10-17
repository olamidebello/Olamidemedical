package health.olamidemedical.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Online hospital client. Patient records remain on the hospital service. */
public final class MainActivity extends Activity {
    private static final String HOME = "https://olamidemedical.health/";
    private WebView web;
    private LinearLayout root;
    private TextView notice;
    private Button retry;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        // Respect system bars when edge-to-edge is enforced on Android 15+.
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        notice = new TextView(this);
        notice.setPadding(24, 24, 24, 24);
        notice.setVisibility(View.GONE);
        retry = new Button(this);
        retry.setText("Retry hospital connection");
        retry.setVisibility(View.GONE);
        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setSaveFormData(false);
        settings.setSupportMultipleWindows(false);
        settings.setUserAgentString(settings.getUserAgentString() + " OlamideMedicalAndroid/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                boolean https = "https".equalsIgnoreCase(uri.getScheme());
                if (https && "olamidemedical.health".equalsIgnoreCase(uri.getHost())
                        && (uri.getPort() == -1 || uri.getPort() == 443)) return false;
                if (request.isForMainFrame() && request.hasGesture() && https) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
                    catch (ActivityNotFoundException ignored) { showError(); }
                }
                return true;
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showError();
            }
        });
        // No SSL-error override, native JavaScript bridge, offline records or background tracking.
        retry.setOnClickListener(v -> {
            notice.setVisibility(View.GONE); retry.setVisibility(View.GONE);
            web.setVisibility(View.VISIBLE); web.loadUrl(HOME);
        });
        root.addView(notice); root.addView(retry);
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        web.loadUrl(HOME);
    }
    private void showError() {
        web.setVisibility(View.GONE);
        notice.setText("Unable to connect securely to Olamide Medical. Check your internet connection and try again.");
        notice.setVisibility(View.VISIBLE); retry.setVisibility(View.VISIBLE);
    }
    @Override public void onBackPressed() { if (web.canGoBack()) web.goBack(); else super.onBackPressed(); }
    @Override protected void onPause() { web.onPause(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }
    @Override protected void onDestroy() { if (web != null) { root.removeView(web); web.destroy(); } super.onDestroy(); }
}
