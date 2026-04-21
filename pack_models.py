import os
import sys
import subprocess
import json
import glob
from PIL import Image
from io import BytesIO
from collections import OrderedDict

from model_helpers_paths import WWRANDO_PATH, SUPERBMD_PATH

sys.path.insert(0, WWRANDO_PATH)
from fs_helpers import *
from wwlib.rarc import RARC
from wwlib.texture_utils import *
from wwlib.bti import *
from wwlib.j3d import ColorAnimation, AnimationTrack, AnimationKeyframe, LoopMode, TangentType

class ModelConversionError(Exception):
    pass

def file_is_newer(file1, file2):
    """Return True if file1 is newer than file2"""
    return os.path.getmtime(file1) > os.path.getmtime(file2)

def should_convert_model(dae_path, bmd_path, related_files):
    if not os.path.exists(bmd_path):
        return True
    dae_mtime = os.path.getmtime(dae_path)
    for rel in related_files:
        if os.path.exists(rel) and os.path.getmtime(rel) > os.path.getmtime(bmd_path):
            return True
    if dae_mtime > os.path.getmtime(bmd_path):
        return True
    return False

def convert_model(model_name, input_dir, output_dir):
    in_dae_path = os.path.join(input_dir, f"{model_name}.dae")
    out_bmd_path = os.path.join(output_dir, f"{model_name}.bmd")
    tex_headers_path = os.path.join(input_dir, f"{model_name}_tex_headers.json")
    materials_path = os.path.join(input_dir, f"{model_name}_materials.json")

    if not os.path.exists(in_dae_path):
        print(f"Missing: {in_dae_path}")
        return

    related_files = [tex_headers_path, materials_path]
    if not should_convert_model(in_dae_path, out_bmd_path, related_files):
        print(f"Skipping: {model_name} (up to date)")
        return

    command = [
        SUPERBMD_PATH,
        in_dae_path,
        out_bmd_path,
        "-x", tex_headers_path,
        "-m", materials_path
    ]

    # Add degeneratetri and -t all flags only for non-hands models
    if model_name not in ("al_hands", "bl_hands"):
        command += ["--degeneratetri", "-t", "all"]

    print(f"Converting: {model_name}")
    result = subprocess.run(command)
    if result.returncode != 0:
        raise ModelConversionError(f"SuperBMD failed for {model_name}")

def unpack_sections(bdl_path):
    with open(bdl_path, "rb") as f:
        data = BytesIO(f.read())
    return unpack_sections_by_data(data)

def unpack_sections_by_data(data):
    bdl_size = data_len(data)
    sections = OrderedDict()
    sections["header"] = BytesIO(read_bytes(data, 0, 0x20))
    offset = 0x20
    while offset < bdl_size:
        section_magic = read_str(data, offset, 4)
        section_size = read_u32(data, offset+4)
        sections[section_magic] = BytesIO(read_bytes(data, offset, section_size))
        offset += section_size
    return sections

def pack_sections(sections):
    data = BytesIO()
    for section_name, section_data in sections.items():
        section_data.seek(0)
        data.write(section_data.read())
    return data

def copy_original_sections(out_bdl_path, orig_bdl_path, sections_to_copy):
    sections = unpack_sections(out_bdl_path)
    orig_sections = unpack_sections(orig_bdl_path)
    for section_magic in sections_to_copy:
        sections[section_magic] = orig_sections[section_magic]
    data = pack_sections(sections)
    size = data_len(data)
    write_u32(data, 8, size)
    with open(out_bdl_path, "wb") as f:
        data.seek(0)
        f.write(data.read())
    return data

def convert_all_player_models(orig_link_folder, custom_player_folder, rarc_name="Kmdl.arc", no_skip_unchanged=False):
    orig_link_arc_path = os.path.join(orig_link_folder, rarc_name)
    with open(orig_link_arc_path, "rb") as f:
        rarc_data = BytesIO(f.read())
    link_arc = RARC()
    link_arc.read(rarc_data)

    all_model_basenames = []
    all_texture_basenames = []
    all_bone_anim_basenames = []
    all_tev_anim_basenames = []
    all_tex_anim_basenames = []
    all_btp_anim_basenames = []
    all_bas_anim_basenames = []
    all_bpk_anim_basenames = []

    for file_entry in link_arc.file_entries:
        if file_entry.is_dir:
            continue
        basename, file_ext = os.path.splitext(file_entry.name)
        if file_ext == ".bmd":
            all_model_basenames.append(basename)
        if file_ext == ".bti":
            all_texture_basenames.append(basename)
        if file_ext == ".bck":
            all_bone_anim_basenames.append(basename)
        if file_ext == ".brk":
            all_tev_anim_basenames.append(basename)
        if file_ext == ".btk":
            all_tex_anim_basenames.append(basename)
        if file_ext == ".btp":
            all_btp_anim_basenames.append(basename)
        if file_ext == ".bas":
            all_bas_anim_basenames.append(basename)
        if file_ext == ".bpk":
            all_bpk_anim_basenames.append(basename)

    found_any_files_to_modify = False

    # Convert all models including al_hands and bl_hands
    for model_basename in all_model_basenames:
        new_model_folder = os.path.join(custom_player_folder, model_basename)
        if os.path.isdir(new_model_folder):
            out_bdl_path = os.path.join(new_model_folder, model_basename + ".bmd")

            should_rebuild_bdl = no_skip_unchanged
            if not should_rebuild_bdl and os.path.isfile(out_bdl_path):
                last_compile_time = os.path.getmtime(out_bdl_path)
                relevant_file_exts = ["dae", "png", "json"]
                for file_ext in relevant_file_exts:
                    relevant_file_paths = glob.glob(os.path.join(new_model_folder, "*." + file_ext))
                    for relevant_file_path in relevant_file_paths:
                        if os.path.getmtime(relevant_file_path) > last_compile_time:
                            should_rebuild_bdl = True
                            break
                    if should_rebuild_bdl:
                        break
            else:
                should_rebuild_bdl = True

            if should_rebuild_bdl:
                try:
                    convert_model(model_basename, new_model_folder, new_model_folder)
                except ModelConversionError as e:
                    print(e)
                    sys.exit(1)
            else:
                print(f"Skipping {model_basename} (up to date)")

            orig_bdl_path = os.path.join(orig_link_folder, model_basename, model_basename + ".bmd")

            sections_to_copy = []
            if rarc_name.lower() in ["bmdl.arc", "kmdl.arc", "mmdl.arc", "zmdl.arc", "wmdl.arc", "alanm.arc", "alink.arc"]:
                sections_to_copy += ["INF1", "JNT1"]
            if rarc_name.lower().endswith(".arc"):
                sections_to_copy += ["INF1", "JNT1"]

            link_arc.get_file_entry(model_basename + ".bmd").data = copy_original_sections(out_bdl_path, orig_bdl_path, sections_to_copy)
            found_any_files_to_modify = True

    for texture_basename in all_texture_basenames:
        # Create texture BTI from PNG
        texture_bti_path = os.path.join(custom_player_folder, texture_basename + ".bti")
        texture_png_path = os.path.join(custom_player_folder, texture_basename + ".png")
        if os.path.isfile(texture_png_path):
            found_any_files_to_modify = True
            print(f"Converting {texture_basename} from PNG to BTI")
            image = Image.open(texture_png_path)
            texture = link_arc.get_file(texture_basename + ".bti")

            tex_header_json_path = os.path.join(custom_player_folder, texture_basename + "_tex_header.json")
            if os.path.isfile(tex_header_json_path):
                with open(tex_header_json_path) as f:
                    tex_header = json.load(f)

                if "Format" in tex_header:
                    texture.image_format = ImageFormat[tex_header["Format"]]
                if "PaletteFormat" in tex_header:
                    texture.palette_format = PaletteFormat[tex_header["PaletteFormat"]]
                if "WrapS" in tex_header:
                    texture.wrap_s = WrapMode[tex_header["WrapS"]]
                if "WrapT" in tex_header:
                    texture.wrap_t = WrapMode[tex_header["WrapT"]]
                if "MagFilter" in tex_header:
                    texture.mag_filter = FilterMode[tex_header["MagFilter"]]
                if "MinFilter" in tex_header:
                    texture.min_filter = FilterMode[tex_header["MinFilter"]]
                if "AlphaSetting" in tex_header:
                    texture.alpha_setting = tex_header["AlphaSetting"]
                if "LodBias" in tex_header:
                    texture.lod_bias = tex_header["LodBias"]
                if "unknown2" in tex_header:
                    texture.min_lod = (tex_header["unknown2"] & 0xFF00) >> 8
                    texture.max_lod = (tex_header["unknown2"] & 0x00FF)
                if "MinLOD" in tex_header:
                    texture.min_lod = tex_header["MinLOD"]
                if "MaxLOD" in tex_header:
                    texture.max_lod = tex_header["MaxLOD"]
                if "unknown3" in tex_header:
                    texture.unknown_3 = tex_header["unknown3"]

            texture.replace_image(image)
            texture.save_changes()
            with open(texture_bti_path, "wb") as f:
                texture.file_entry.data.seek(0)
                f.write(texture.file_entry.data.read())

        # Import texture BTI
        if os.path.isfile(texture_bti_path):
            found_any_files_to_modify = True
            with open(texture_bti_path, "rb") as f:
                data = BytesIO(f.read())
            link_arc.get_file_entry(texture_basename + ".bti").data = data


    link_arc.save_changes()
    link_arc_out_path = os.path.join(custom_player_folder, rarc_name)
    with open(link_arc_out_path, "wb") as f:
        link_arc.data.seek(0)
        f.write(link_arc.data.read())

    if not found_any_files_to_modify:
        print("No models, textures, or animations to modify found. Repacked RARC with no changes.")

def load_brk_from_json(brk, input_json_path):
    trk1 = brk.trk1

    with open(input_json_path) as f:
        json_dict = json.load(f)

    trk1.loop_mode = LoopMode[json_dict["LoopMode"]]
    trk1.duration = json_dict["Duration"]
    reg_anims_json = json_dict["RegisterAnimations"]
    konst_anims_json = json_dict["KonstantAnimations"]
    trk1.mat_name_to_reg_anims.clear()
    trk1.mat_name_to_konst_anims.clear()

    for anims_json, anims_dict in [(reg_anims_json, trk1.mat_name_to_reg_anims), (konst_anims_json, trk1.mat_name_to_konst_anims)]:
        for mat_name, mat_anims_json in anims_json.items():
            if mat_name in anims_dict:
                raise Exception(f"Duplicate material name in BRK: \"{mat_name}\"")
            anims_dict[mat_name] = []
            for anim_json in mat_anims_json:
                anim = ColorAnimation()
                anim.color_id = anim_json["ColorID"]
                anims_dict[mat_name].append(anim)
                for channel in ["R", "G", "B", "A"]:
                    track_json = anim_json[channel]
                    anim_track = AnimationTrack()
                    setattr(anim, channel.lower(), anim_track)
                    anim_track.tangent_type = TangentType[track_json["TangentType"]]
                    anim_track.keyframes = []
                    for keyframe_json in track_json["KeyFrames"]:
                        time = keyframe_json["Time"]
                        value = keyframe_json["Value"]
                        tangent_in = keyframe_json["TangentIn"]
                        tangent_out = keyframe_json["TangentOut"]
                        keyframe = AnimationKeyframe(time, value, tangent_in, tangent_out)
                        anim_track.keyframes.append(keyframe)

if __name__ == "__main__":
    args_valid = False
    rarc_name = None
    no_skip_unchanged = False

    if len(sys.argv) >= 5 and sys.argv[1] == "-clean" and sys.argv[3] == "-custom":
        args_valid = True

    extra_args = sys.argv[5:]

    if "-rarcname" in extra_args:
        rarcname_index = extra_args.index("-rarcname")
        if rarcname_index+1 >= len(extra_args):
            args_valid = False
        else:
            rarc_name = extra_args.pop(rarcname_index+1)
            extra_args.remove("-rarcname")

    if "-noskipunchanged" in extra_args:
        no_skip_unchanged = True
        extra_args.remove("-noskipunchanged")

    if extra_args:
        # Invalid extra args
        args_valid = False

    if not args_valid:
        print("The format for running pack_models is as follows:")
        print("  pack_models -clean \"Path/To/Clean/Model/Folder\" -custom \"Path/To/Custom/Model/Folder\"")
        print("Optional arguments:")
        print("  -rarcname <filename>   Specify the RARC filename if multiple .arc files exist")
        print("  -noskipunchanged       Recompile all models, even unchanged ones")
        sys.exit(1)

    orig_link_folder = sys.argv[2]
    custom_player_folder = sys.argv[4]

    # <-- FIXED ARC LOGIC START -->
    if rarc_name is None:
        found_rarcs = []
        for filename in os.listdir(orig_link_folder):
            file_path = os.path.join(orig_link_folder, filename)
            if os.path.isfile(file_path) and os.path.splitext(filename)[1] == ".arc":
                found_rarcs.append(filename)
        if len(found_rarcs) == 1:
            rarc_name = found_rarcs[0]
        elif len(found_rarcs) > 1:
            print("Multiple .arc files found in the clean folder. You must specify which one to use with -rarcname.")
            sys.exit(1)
        else:
            print("No .arc files found in the clean folder.")
            sys.exit(1)
    # <-- FIXED ARC LOGIC END -->

    convert_all_player_models(orig_link_folder, custom_player_folder, rarc_name, no_skip_unchanged)
