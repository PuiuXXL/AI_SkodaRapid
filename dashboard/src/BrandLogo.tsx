export function BrandLogo({dark=true,compact=false}:{dark?:boolean;compact?:boolean}){
  const variant=compact?"symbol":"full";
  return <img src={`/brand/drivemate_${variant}_${dark?"dark":"light"}.svg`}
    alt="DriveMate" width={compact?38:156} height={compact?31:42}
    style={{display:"block",maxWidth:"100%",objectFit:"contain"}}/>;
}
