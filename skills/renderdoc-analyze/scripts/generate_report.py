"""
RenderDoc分析报告生成工具

用法:
    python generate_report.py --output "C:/Users/xxx/Documents" --name "场景渲染" --image-path "C:/path/to/texture.png"

功能:
    1. 创建报告文件夹（格式: {截帧名}_分析报告）
    2. 拷贝最终渲染截图到文件夹内（统一命名为 final_capture.png）
    3. 创建空白MD报告文件
    4. 输出MD文件的绝对路径，供后续写入报告内容
"""

import argparse
import shutil
from pathlib import Path


def create_report_folder(output_path: str, capture_name: str) -> Path:
    """
    创建报告文件夹
    
    Args:
        output_path: 保存路径
        capture_name: 截帧名称
        
    Returns:
        报告文件夹路径
    """
    folder_name = f"{capture_name}_分析报告"
    folder_path = Path(output_path) / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def copy_final_capture(image_source_path: str, report_folder: Path) -> str:
    """
    拷贝最终渲染截图到报告文件夹
    
    Args:
        image_source_path: 源图片路径
        report_folder: 报告文件夹路径
        
    Returns:
        目标图片文件名（用于MD引用）
    """
    target_filename = "final_capture.png"
    target_path = report_folder / target_filename
    
    if Path(image_source_path).exists():
        shutil.copy2(image_source_path, target_path)
        print(f"[OK] 截图已拷贝: {target_path}")
    else:
        print(f"[WARN] 警告: 源图片不存在: {image_source_path}")
        
    return target_filename


def create_empty_report(report_folder: Path) -> Path:
    """
    创建空白MD报告文件
    
    Args:
        report_folder: 报告文件夹路径
        
    Returns:
        MD文件绝对路径
    """
    md_filename = "RenderDoc_分析报告.md"
    md_path = report_folder / md_filename
    
    # 创建空白文件
    md_path.touch()
    
    print(f"[OK] 空白报告已创建: {md_path}")
    return md_path


def main():
    parser = argparse.ArgumentParser(description='生成RenderDoc分析报告')
    parser.add_argument('--output', required=True, help='保存路径')
    parser.add_argument('--name', required=True, help='截帧名称')
    parser.add_argument('--image-path', required=True, help='最终渲染截图源路径')
    
    args = parser.parse_args()
    
    print(f"\n=== RenderDoc 报告生成工具 ===")
    print(f"输出路径: {args.output}")
    print(f"截帧名称: {args.name}")
    print(f"源图片: {args.image_path}\n")
    
    # 1. 创建报告文件夹
    report_folder = create_report_folder(args.output, args.name)
    print(f"[OK] 报告文件夹已创建: {report_folder}")
    
    # 2. 拷贝最终渲染截图
    copy_final_capture(args.image_path, report_folder)
    
    # 3. 创建空白MD文件
    md_path = create_empty_report(report_folder)
    
    print(f"\n[OK] 报告准备完成！")
    print(f"  文件夹: {report_folder}")
    print(f"  报告文件: {md_path}\n")


if __name__ == '__main__':
    main()
