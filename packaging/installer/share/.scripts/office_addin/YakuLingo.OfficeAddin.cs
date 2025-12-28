using System;
using System.Diagnostics;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;
using Extensibility;

[assembly: ComVisible(true)]
[assembly: Guid("5F5C7D1D-2F4D-4A2E-BBBA-3B4E7844F5E8")]
[assembly: System.Reflection.AssemblyTitle("YakuLingo Office COM Add-in")]
[assembly: System.Reflection.AssemblyProduct("YakuLingo")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

namespace YakuLingo.OfficeAddin
{
    [ComVisible(true)]
    [Guid("000C0396-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IRibbonExtensibility
    {
        string GetCustomUI(string RibbonID);
    }

    [ComVisible(true)]
    [Guid("2BD0EC3D-2947-4873-923C-BF4FC30DB4CB")]
    [ProgId("YakuLingo.OfficeAddin")]
    [ClassInterface(ClassInterfaceType.None)]
    public sealed class YakuLingoAddin : IDTExtensibility2, IRibbonExtensibility
    {
        private const int ApiPort = 8765;
        private const string ApiUrl = "http://127.0.0.1:8765/api/hotkey";
        private const string RegistryKeyPath = @"Software\YakuLingo";
        private const string RegistryValueSetupPath = "SetupPath";

        private object _application;
        private string _hostProcessName;

        public void OnConnection(object Application, ext_ConnectMode ConnectMode, object AddInInst, ref Array custom)
        {
            _application = Application;
            try
            {
                _hostProcessName = Process.GetCurrentProcess().ProcessName;
            }
            catch
            {
                _hostProcessName = string.Empty;
            }
        }

        public void OnDisconnection(ext_DisconnectMode RemoveMode, ref Array custom)
        {
            _application = null;
        }

        public void OnAddInsUpdate(ref Array custom) { }
        public void OnStartupComplete(ref Array custom) { }
        public void OnBeginShutdown(ref Array custom) { }

        public string GetCustomUI(string RibbonID)
        {
            return
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
                "<customUI xmlns=\"http://schemas.microsoft.com/office/2009/07/customui\">" +
                "  <ribbon>" +
                "    <tabs>" +
                "      <tab id=\"yakulingoTab\" label=\"YakuLingo\">" +
                "        <group id=\"yakulingoGroup\" label=\"翻訳\">" +
                "          <button id=\"yakulingoTranslate\" label=\"YakuLingoで翻訳\" size=\"large\" imageMso=\"Translate\" onAction=\"OnTranslate\" />" +
                "        </group>" +
                "      </tab>" +
                "    </tabs>" +
                "  </ribbon>" +
                "</customUI>";
        }

        public void OnTranslate(object control)
        {
            try
            {
                var payload = GetPayload();
                if (string.IsNullOrWhiteSpace(payload))
                {
                    ShowInfo("翻訳するテキストを選択してください。");
                    return;
                }
                var captured = payload;
                Task.Run(() => TriggerTranslationSafe(captured));
            }
            catch (Exception ex)
            {
                ShowError("翻訳の実行に失敗しました。", ex);
            }
        }

        private void TriggerTranslationSafe(string payload)
        {
            try
            {
                EnsureYakuLingoRunning();
                PostHotkey(payload);
            }
            catch (Exception ex)
            {
                ShowError("YakuLingo に送信できませんでした。", ex);
            }
        }

        private string GetPayload()
        {
            var host = (_hostProcessName ?? string.Empty).ToUpperInvariant();
            if (host == "OUTLOOK") return GetOutlookText();
            if (host == "WINWORD") return GetWordSelectionText();
            if (host == "EXCEL") return GetExcelSelectionText();
            if (host == "POWERPNT") return GetPowerPointSelectionText();

            // Fallback: try Word-like Selection.Text (works in some hosts)
            try
            {
                dynamic app = _application;
                var text = app.Selection.Text as string;
                if (!string.IsNullOrWhiteSpace(text)) return text.Trim();
            }
            catch { }

            return null;
        }

        private string GetWordSelectionText()
        {
            try
            {
                dynamic app = _application;
                var text = app.Selection.Text as string;
                if (string.IsNullOrWhiteSpace(text)) return null;
                return text.Trim();
            }
            catch
            {
                return null;
            }
        }

        private string GetExcelSelectionText()
        {
            try
            {
                dynamic app = _application;
                dynamic range = app.Selection;
                object value = range.Value2;
                if (value == null) return null;

                var arr = value as Array;
                if (arr != null && arr.Rank == 2)
                {
                    return Join2DArray(arr);
                }

                var text = Convert.ToString(value);
                if (string.IsNullOrWhiteSpace(text)) return null;
                return text.Trim();
            }
            catch
            {
                return null;
            }
        }

        private static string Join2DArray(Array arr)
        {
            var sb = new StringBuilder();
            try
            {
                int r0 = arr.GetLowerBound(0);
                int r1 = arr.GetUpperBound(0);
                int c0 = arr.GetLowerBound(1);
                int c1 = arr.GetUpperBound(1);
                for (int r = r0; r <= r1; r++)
                {
                    bool hasRowContent = false;
                    var row = new StringBuilder();
                    for (int c = c0; c <= c1; c++)
                    {
                        object cell = null;
                        try { cell = arr.GetValue(r, c); } catch { cell = null; }
                        var cellText = cell == null ? string.Empty : Convert.ToString(cell);
                        if (!string.IsNullOrEmpty(cellText)) hasRowContent = true;
                        if (c > c0) row.Append('\t');
                        row.Append(cellText);
                    }
                    if (!hasRowContent) continue;
                    if (sb.Length > 0) sb.AppendLine();
                    sb.Append(row.ToString().TrimEnd());
                }
            }
            catch { }
            var result = sb.ToString().Trim();
            return string.IsNullOrWhiteSpace(result) ? null : result;
        }

        private string GetPowerPointSelectionText()
        {
            try
            {
                dynamic app = _application;
                dynamic sel = app.ActiveWindow.Selection;

                // 1) Direct TextRange (text cursor / selected text)
                try
                {
                    var text = sel.TextRange.Text as string;
                    if (!string.IsNullOrWhiteSpace(text)) return text.Trim();
                }
                catch { }

                // 2) Selected shapes
                try
                {
                    dynamic shapes = sel.ShapeRange;
                    int count = (int)shapes.Count;
                    var sb = new StringBuilder();
                    for (int i = 1; i <= count; i++)
                    {
                        dynamic shape = shapes.Item(i);
                        try
                        {
                            dynamic tf = shape.TextFrame;
                            int hasText = Convert.ToInt32(tf.HasText);
                            if (hasText == 0) continue;
                            var t = tf.TextRange.Text as string;
                            if (string.IsNullOrWhiteSpace(t)) continue;
                            if (sb.Length > 0) sb.AppendLine();
                            sb.Append(t.Trim());
                        }
                        catch { }
                    }
                    if (sb.Length > 0) return sb.ToString();
                }
                catch { }

                return null;
            }
            catch
            {
                return null;
            }
        }

        private string GetOutlookText()
        {
            dynamic app = _application;

            // 1) Inspector: selected text if available, else current mail body
            try
            {
                dynamic inspector = app.ActiveInspector();
                if (inspector != null)
                {
                    // Selected text in Word editor
                    try
                    {
                        dynamic doc = inspector.WordEditor;
                        dynamic sel = doc.Application.Selection;
                        var selected = sel.Text as string;
                        if (!string.IsNullOrWhiteSpace(selected)) return selected.Trim();
                    }
                    catch { }

                    // Fallback: current item body
                    try
                    {
                        dynamic item = inspector.CurrentItem;
                        if (item != null)
                        {
                            var subject = item.Subject as string;
                            var body = item.Body as string;
                            var merged = MergeSubjectBody(subject, body);
                            if (!string.IsNullOrWhiteSpace(merged)) return merged.Trim();
                        }
                    }
                    catch { }
                }
            }
            catch { }

            // 2) Explorer: selected mail body
            try
            {
                dynamic explorer = app.ActiveExplorer();
                if (explorer != null)
                {
                    dynamic selection = explorer.Selection;
                    int count = (int)selection.Count;
                    if (count >= 1)
                    {
                        dynamic item = selection.Item(1);
                        var subject = item.Subject as string;
                        var body = item.Body as string;
                        var merged = MergeSubjectBody(subject, body);
                        if (!string.IsNullOrWhiteSpace(merged)) return merged.Trim();
                    }
                }
            }
            catch { }

            return null;
        }

        private static string MergeSubjectBody(string subject, string body)
        {
            subject = string.IsNullOrWhiteSpace(subject) ? null : subject.Trim();
            body = string.IsNullOrWhiteSpace(body) ? null : body.Trim();
            if (subject == null) return body;
            if (body == null) return subject;
            return subject + "\r\n\r\n" + body;
        }

        private void EnsureYakuLingoRunning()
        {
            if (IsPortOpen(ApiPort, 200)) return;

            var setupPath = GetSetupPath();
            if (string.IsNullOrWhiteSpace(setupPath)) return;

            try
            {
                var exePath = System.IO.Path.Combine(setupPath, "YakuLingo.exe");
                if (System.IO.File.Exists(exePath))
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = exePath,
                        WorkingDirectory = setupPath,
                        UseShellExecute = true,
                    });
                }
                else
                {
                    var pythonw = System.IO.Path.Combine(setupPath, ".venv", "Scripts", "pythonw.exe");
                    var appPy = System.IO.Path.Combine(setupPath, "app.py");
                    if (System.IO.File.Exists(pythonw) && System.IO.File.Exists(appPy))
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = pythonw,
                            Arguments = "\"" + appPy + "\"",
                            WorkingDirectory = setupPath,
                            UseShellExecute = false,
                            CreateNoWindow = true,
                        });
                    }
                }
            }
            catch { }

            var sw = Stopwatch.StartNew();
            while (sw.Elapsed < TimeSpan.FromSeconds(15))
            {
                if (IsPortOpen(ApiPort, 200)) return;
                Thread.Sleep(200);
            }
        }

        private static bool IsPortOpen(int port, int timeoutMs)
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var task = client.ConnectAsync("127.0.0.1", port);
                    if (!task.Wait(timeoutMs)) return false;
                    return client.Connected;
                }
            }
            catch
            {
                return false;
            }
        }

        private static string GetSetupPath()
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(RegistryKeyPath))
                {
                    if (key != null)
                    {
                        var value = key.GetValue(RegistryValueSetupPath) as string;
                        if (!string.IsNullOrWhiteSpace(value)) return value.Trim();
                    }
                }
            }
            catch { }

            try
            {
                return System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "YakuLingo"
                );
            }
            catch
            {
                return null;
            }
        }

        private static void PostHotkey(string payload)
        {
            var json = "{\"payload\":\"" + JsonEscape(payload) + "\",\"open_ui\":true}";
            using (var client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromSeconds(3);
                using (var content = new StringContent(json, Encoding.UTF8, "application/json"))
                {
                    var response = client.PostAsync(ApiUrl, content).GetAwaiter().GetResult();
                    response.EnsureSuccessStatusCode();
                }
            }
        }

        private static string JsonEscape(string value)
        {
            if (value == null) return string.Empty;
            var sb = new StringBuilder(value.Length + 16);
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"': sb.Append("\\\""); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20)
                        {
                            sb.Append("\\u");
                            sb.Append(((int)c).ToString("x4"));
                        }
                        else
                        {
                            sb.Append(c);
                        }
                        break;
                }
            }
            return sb.ToString();
        }

        private static void ShowInfo(string message)
        {
            try
            {
                MessageBox.Show(message, "YakuLingo", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch { }
        }

        private static void ShowError(string message, Exception ex)
        {
            try
            {
                var details = ex == null ? string.Empty : ("\r\n\r\n" + ex.GetType().Name + ": " + ex.Message);
                MessageBox.Show(message + details, "YakuLingo", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch { }
        }
    }
}
