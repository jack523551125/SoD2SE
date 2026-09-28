#include <windows.h>
#include <shellapi.h>
#include <d3d11.h>
#include <string>
#include <fstream>
#include <vector>

static IDXGISwapChain* swap = nullptr;
static ID3D11Device* device = nullptr;
static ID3D11DeviceContext* context = nullptr;
static ID3D11RenderTargetView* target = nullptr;
static int receivedKeys = 0, polledKeys = 0;
static LRESULT CALLBACK WindowProc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam) {
    if (msg == WM_KEYDOWN && wparam == 'W') ++receivedKeys;
    if (msg == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(hwnd, msg, wparam, lparam);
}
static void Capture(const std::wstring& output) {
    ID3D11Texture2D* buffer = nullptr;
    if (FAILED(swap->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&buffer))) return;
    D3D11_TEXTURE2D_DESC desc{}; buffer->GetDesc(&desc);
    desc.Usage = D3D11_USAGE_STAGING; desc.BindFlags = 0; desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ; desc.MiscFlags = 0;
    ID3D11Texture2D* staging = nullptr;
    if (SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &staging))) {
        context->CopyResource(staging, buffer);
        D3D11_MAPPED_SUBRESOURCE mapped{};
        if (SUCCEEDED(context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped))) {
            BITMAPFILEHEADER file{}; BITMAPINFOHEADER info{};
            file.bfType = 0x4d42; file.bfOffBits = sizeof(file) + sizeof(info);
            file.bfSize = file.bfOffBits + desc.Width * desc.Height * 4;
            info.biSize = sizeof(info); info.biWidth = desc.Width; info.biHeight = -(LONG)desc.Height;
            info.biPlanes = 1; info.biBitCount = 32; info.biCompression = BI_RGB;
            std::ofstream stream(output, std::ios::binary);
            stream.write((char*)&file, sizeof(file)); stream.write((char*)&info, sizeof(info));
            std::vector<unsigned char> row(desc.Width * 4);
            for (UINT y = 0; y < desc.Height; ++y) {
                auto src = (unsigned char*)mapped.pData + y * mapped.RowPitch;
                for (UINT x = 0; x < desc.Width; ++x) {
                    row[x * 4] = src[x * 4 + 2]; row[x * 4 + 1] = src[x * 4 + 1];
                    row[x * 4 + 2] = src[x * 4]; row[x * 4 + 3] = 255;
                }
                stream.write((char*)row.data(), row.size());
            }
            context->Unmap(staging, 0);
        }
        staging->Release();
    }
    buffer->Release();
}
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    int count = 0; auto argv = CommandLineToArgvW(GetCommandLineW(), &count);
    if (count < 2) return 2;
    std::wstring directory = argv[1];
    // Optional "WIDTHxHEIGHT" lets a preview run at a realistic game
    // resolution instead of the default small verification window.
    int windowWidth = 1280, windowHeight = 860;
    if (count >= 3) {
        std::wstring size = argv[2];
        size_t split = size.find(L'x');
        if (split != std::wstring::npos) {
            int width = _wtoi(size.substr(0, split).c_str());
            int height = _wtoi(size.substr(split + 1).c_str());
            if (width >= 640 && height >= 480) { windowWidth = width; windowHeight = height; }
        }
    }
    LocalFree(argv);
    WNDCLASSW cls{}; cls.lpfnWndProc = WindowProc; cls.hInstance = instance; cls.lpszClassName = L"SoD2SE.MCM.Test";
    RegisterClassW(&cls);
    HWND hwnd = CreateWindowExW(0, cls.lpszClassName, L"SoD2SE MCM render verification", WS_OVERLAPPEDWINDOW,
                                40, 40, windowWidth, windowHeight, nullptr, nullptr, instance, nullptr);
    DXGI_SWAP_CHAIN_DESC desc{}; desc.BufferCount = 1; desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; desc.OutputWindow = hwnd;
    desc.SampleDesc.Count = 1; desc.Windowed = TRUE;
    if (FAILED(D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0,
                    D3D11_SDK_VERSION, &desc, &swap, &device, nullptr, &context))) return 3;
    ID3D11Texture2D* buffer = nullptr; swap->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&buffer);
    device->CreateRenderTargetView(buffer, nullptr, &target); buffer->Release();
    ShowWindow(hwnd, SW_SHOW); SetForegroundWindow(hwnd);
    MSG message{}; ULONGLONG started = GetTickCount64();
    while (GetTickCount64() - started < 90000) {
        while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
            if (message.message == WM_QUIT) return 0;
            TranslateMessage(&message); DispatchMessageW(&message);
        }
        if (GetAsyncKeyState('W') & 0x8000) ++polledKeys;
        if (GetFileAttributesW((directory + L"\\input.request").c_str()) != INVALID_FILE_ATTRIBUTES) {
            { std::ofstream stream(directory + L"\\input.txt"); stream << receivedKeys << " " << polledKeys; }
            DeleteFileW((directory + L"\\input.request").c_str());
        }
        if (GetFileAttributesW((directory + L"\\resize.request").c_str()) != INVALID_FILE_ATTRIBUTES) {
            context->OMSetRenderTargets(0, nullptr, nullptr); target->Release(); target = nullptr;
            HRESULT result = swap->ResizeBuffers(0, 1024, 768, DXGI_FORMAT_UNKNOWN, 0);
            if (FAILED(result)) return 4;
            ID3D11Texture2D* resized = nullptr;
            swap->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&resized);
            device->CreateRenderTargetView(resized, nullptr, &target); resized->Release();
            DeleteFileW((directory + L"\\resize.request").c_str());
        }
        float color[4]{.11f, .15f, .18f, 1}; context->OMSetRenderTargets(1, &target, nullptr);
        context->ClearRenderTargetView(target, color);
        if (GetFileAttributesW((directory + L"\\capture.request").c_str()) != INVALID_FILE_ATTRIBUTES) {
            swap->Present(0, DXGI_PRESENT_TEST);
            Capture(directory + L"\\menu.bmp");
            DeleteFileW((directory + L"\\capture.request").c_str());
        }
        swap->Present(1, 0);
        if (GetFileAttributesW((directory + L"\\stop.request").c_str()) != INVALID_FILE_ATTRIBUTES) break;
    }
    return 0;
}
