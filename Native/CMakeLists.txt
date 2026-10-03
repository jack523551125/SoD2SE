cmake_minimum_required(VERSION 3.20)
project(SoD2SERuntimeNativeTests LANGUAGES C CXX)

add_executable(CharacterIdentifierCodecTest tests/Shared/CharacterIdentifierCodecTest.cpp)
target_include_directories(CharacterIdentifierCodecTest PRIVATE src/Shared)
target_compile_features(CharacterIdentifierCodecTest PRIVATE cxx_std_17)
target_compile_options(CharacterIdentifierCodecTest PRIVATE /utf-8 /W4 /WX)

add_executable(PinnedImageTest tests/Shared/PinnedImageTest.cpp)
target_include_directories(PinnedImageTest PRIVATE src/Shared)
target_compile_features(PinnedImageTest PRIVATE cxx_std_17)
target_compile_definitions(PinnedImageTest PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
target_compile_options(PinnedImageTest PRIVATE /utf-8 /W4 /WX /EHa)
target_link_libraries(PinnedImageTest PRIVATE bcrypt)
